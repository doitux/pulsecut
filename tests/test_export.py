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
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


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


@pytest.mark.slow
def test_render_ffmpeg_fallback(projekt, tmp_path):
    prepare(projekt, ziel=75)
    out = tmp_path / "fallback.mp4"
    EX.render_ffmpeg(projekt, out, "720p")
    assert abs(float(probe(out)["format"]["duration"]) - projekt.layout.D) < 1.0
