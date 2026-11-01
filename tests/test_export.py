"""Kdenlive project and rendered videos (melt with crossfades, ffmpeg fallback with hard cuts)."""
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from conftest import prepare
from pulsecut import export as EX
from pulsecut.projekt import Job


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration,size:stream=codec_type,width,height,r_frame_rate,nb_frames",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def profil(path):
    root = ET.parse(path).getroot()
    p = root.find("profile")
    props = {x.get("name"): x.text for x in root.iter("property")}
    return int(p.get("frame_rate_num")), int(p.get("frame_rate_den")), props.get("kdenlive:docproperties.profile")


def titles(pr):
    pr.d["schnitt"].update({"titel": "Camp 2026", "untertitel": "Test", "abspann": "Thanks!"})


def test_kdenlive_project(projekt, tmp_path):
    prepare(projekt, uebergang="blende", blende=0.6)
    titles(projekt)
    out = tmp_path / "film.kdenlive"
    EX.write_project(projekt, out)
    root = ET.parse(out).getroot()
    assert root.tag == "mlt"
    names = [p.text for p in root.iter("property") if p.get("name") == "kdenlive:track_name"]
    assert {"Musik", "Video A", "Video B", "Titel"} <= set(names), names
    entries = sum(1 for pl in root.iter("playlist") for _ in pl.iter("entry"))
    assert entries > len(projekt.d["timeline"])


def test_kdenlive_project_english(projekt, tmp_path):
    from pulsecut.i18n import set_lang
    prepare(projekt)
    set_lang("en", persist=False)
    try:
        out = tmp_path / "film_en.kdenlive"
        EX.write_project(projekt, out)
    finally:
        set_lang("de", persist=False)
    names = [p.text for p in ET.parse(out).getroot().iter("property") if p.get("name") == "kdenlive:track_name"]
    assert "Music" in names and "Titles" in names


def test_frame_rate_follows_the_videos(projekt, tmp_path):
    """The synthetic videos are 30 fps → the Kdenlive project is 30 fps (not 25), the music cuts lie on its frames;
    chosen by hand it can be something else."""
    prepare(projekt)
    projekt.d.pop("export", None)
    projekt.update_layout()
    br = projekt.bildrate()
    assert br["key"] == "30" and br["auto"] and br["verteilung"]["30"] > 0.9
    assert projekt.layout.fps == 30
    for sg in projekt.layout.segments:
        assert abs(sg["tl_start"] * 30 - round(sg["tl_start"] * 30)) < 1e-6
    out = tmp_path / "f30.kdenlive"
    EX.write_project(projekt, out)
    assert profil(out) == (30, 1, "atsc_1080p_30")
    seq = [x for x in ET.parse(out).getroot().iter("property") if x.get("name") == "kdenlive:maxduration"]
    assert seq and abs(int(seq[0].text) - round(projekt.layout.D * 30)) <= 1
    assert EX.FPS == 25            # only during the export
    for key, want in (("2997", (30000, 1001, "atsc_1080p_2997")), ("25", (25, 1, "atsc_1080p_25")),
                      ("60", (60, 1, "atsc_1080p_60"))):
        info = projekt.export_setzen({"bildrate": key})
        assert info["bildrate"]["key"] == key and not info["bildrate"]["auto"]
        assert abs(projekt.layout.fps - want[0] / want[1]) < 1e-9
        EX.write_project(projekt, out)
        assert profil(out) == want
    projekt.export_setzen({"bildrate": "auto"})
    assert projekt.bildrate()["key"] == "30" and projekt.layout.fps == 30
    assert problems_free(projekt)


def problems_free(pr):
    from pulsecut import planer as PL
    tl, diff = pr.relayout()
    return diff == 0 and not [p for p in PL.check(tl, pr.clip_by_name(), pr.xf()) if p["art"] in ("ueberlappung", "rand")]


def test_quality_settings():
    q = EX.qualitaet({"stufe": "web", "crf": 23})
    assert q["stufe"] == "web" and q["crf"] == 23 and q["modus"] == "qualitaet"
    assert EX.qualitaet({"stufe": "web", "crf": 21})["stufe"] == ""            # slider moved: own setting
    assert EX.qualitaet({"crf": 99})["crf"] == EX.CRF_BEREICH[1] and EX.qualitaet({"crf": 1})["crf"] == EX.CRF_BEREICH[0]
    D = 180.0
    groessen = [EX.schaetzung_mb("1080p", D, EX.qualitaet({"stufe": k, "crf": v["crf"]}), 30) for k, v in EX.STUFEN.items()]
    assert groessen == sorted(groessen) and groessen[0] > 0          # web < standard < beamer < highest
    assert EX.schaetzung_mb("4k", D, EX.qualitaet({}), 30) > EX.schaetzung_mb("1080p", D, EX.qualitaet({}), 30) \
        > EX.schaetzung_mb("720p", D, EX.qualitaet({}), 30)
    z = EX.qualitaet({"modus": "groesse", "mb": 100})
    assert EX.schaetzung_mb("1080p", D, z, 30) == 100
    assert "vb=" in " ".join(EX.melt_args("1080p", D, z)) and "crf=" not in " ".join(EX.melt_args("1080p", D, z))
    assert "crf=17" in EX.melt_args("1080p", D, EX.qualitaet({"stufe": "beamer", "crf": 17}))
    # 100 MB for 3 min 1080p is plenty, 5 MB is visibly too little
    assert EX.zielgroesse_wie("1080p", D, z, 30) in EX.STUFEN
    assert EX.zielgroesse_wie("1080p", D, EX.qualitaet({"modus": "groesse", "mb": 5}), 30) == "knapp"


@pytest.mark.slow
def test_render_target_size_and_30fps(projekt, tmp_path):
    """Target size is met roughly, the film has the frame rate of the videos (melt and the ffmpeg fallback)."""
    prepare(projekt, ziel=60)
    projekt.d.pop("export", None)
    projekt.update_layout()
    projekt.export_setzen({"modus": "groesse", "mb": 8})
    job = Job("export")
    projekt.export_job(job, ["720p"], kdenlive=False)
    mp4 = next(p for p in projekt.d["exporte"] if p.endswith(".mp4"))
    info = probe(mp4)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert v["r_frame_rate"] == "30/1", v
    mb = int(info["format"]["size"]) / 1024 / 1024
    assert 8 * 0.4 < mb < 8 * 1.1, mb           # at most about the target (calm test footage: smaller)
    out = tmp_path / "fallback.mp4"
    EX.render_ffmpeg(projekt, out, "720p", q=projekt.d["export"]["qualitaet"])
    info = probe(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert v["r_frame_rate"] == "30/1", v
    assert abs(float(info["format"]["duration"]) - projekt.layout.D) < 0.5
    assert 8 * 0.4 < int(info["format"]["size"]) / 1024 / 1024 < 8 * 1.1
    projekt.d.pop("export", None)


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["hart", "blende"])
def test_render_720p(projekt, mode):
    if mode == "blende" and not shutil.which("melt"):
        pytest.skip("melt not installed")
    prepare(projekt, ziel=75, uebergang=mode, blende=0.6)
    assert abs(projekt.layout.D - 75) < 5
    titles(projekt)
    job = Job("export")
    projekt.export_job(job, ["720p"], kdenlive=True)
    mp4 = next(p for p in projekt.d["exporte"] if p.endswith(".mp4"))
    info = probe(mp4)
    video = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (video["width"], video["height"]) == (1280, 720)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - projekt.layout.D) < 1.0
    assert video["r_frame_rate"] == "30/1", video                      # like the videos, not 25
    assert 0.2 <= projekt.d["export"]["faktor"] <= 5                    # size estimate calibrated on this footage


@pytest.mark.slow
def test_render_ffmpeg_fallback(projekt, tmp_path):
    prepare(projekt, ziel=75)
    out = tmp_path / "fallback.mp4"
    EX.render_ffmpeg(projekt, out, "720p")
    assert abs(float(probe(out)["format"]["duration"]) - projekt.layout.D) < 1.0
