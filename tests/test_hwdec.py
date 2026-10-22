"""Single ffmpeg pass (analysis + preview + sound) and decoding on the graphics chip.

The test machines have no graphics chip, so the chip path is played with software stand-ins
(PULSECUT_HWDEC_EMUL=1: no automatic rotation, own rotation filter, scaling before the rotation – exactly the
structure of the VAAPI graph) or made to fail (=fail)."""
import json
import shutil
import subprocess

import numpy as np
import pytest

from pulsecut import hwdec as HW
from pulsecut import video as V


@pytest.fixture
def emul(monkeypatch):
    def set_(mode):
        monkeypatch.setenv("PULSECUT_HWDEC_EMUL", mode)
        HW.zuruecksetzen()
    yield set_
    monkeypatch.delenv("PULSECUT_HWDEC_EMUL", raising=False)
    HW.zuruecksetzen()


def _dirs(base):
    d = {k: base / k for k in ("bilder", "deskriptoren", "proxy")}
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


def _clip(path):
    c = V.Clip(path, 0)
    c.probe()
    return c


def _same(a, b, tol=1e-9):
    bad = []
    for k in a:
        if k == "ki_frames":
            continue
        x, y = a[k], b[k]
        if isinstance(x, list) and x and not isinstance(x[0], (dict, list)):
            if len(x) != len(y) or np.max(np.abs(np.array(x, float) - np.array(y, float))) > tol:
                bad.append(k)
        elif json.dumps(x) != json.dumps(y):
            bad.append(k)
    return bad


def _dims(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
    return tuple(int(x) for x in out.split(","))


def _frame(p, t=1.0):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(p), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).astype(float)


@pytest.fixture(scope="module")
def rotated(media, tmp_path_factory):
    """A portrait phone video: landscape picture with a 90° display rotation."""
    src = sorted(media.RAW.glob("VID_*.mp4"))[0]
    out = tmp_path_factory.mktemp("rot") / "VID_rot.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(src), "-c", "copy", str(out)],
                   check=True)
    return out


def test_probe_stores_codec_and_rotation(media, rotated):
    c = _clip(sorted(media.RAW.glob("VID_*.mp4"))[0])
    assert c.codec == "h264" and c.pix and c.rot == 0
    r = _clip(rotated)
    assert r.rot in (90, -90) and r.h > r.w
    m = r.to_meta()
    r2 = V.Clip(rotated, 0)
    r2.from_meta(m)
    assert (r2.codec, r2.pix, r2.rot) == (r.codec, r.pix, r.rot)


def test_single_pass_gives_the_same_result(media, tmp_path):
    c = _clip(sorted(media.RAW.glob("VID_*.mp4"))[2])
    assert c.has_audio
    a = V.analyse_clip(c, _dirs(tmp_path / "a"))
    proxy = _dirs(tmp_path / "b")["proxy"] / "p.webm"
    b = V.analyse_clip(c, _dirs(tmp_path / "b"), proxy=proxy)
    assert _same(a, b) == []
    assert a["ton"] == V.analyse_audio_dsp(c.path)       # the sound read along is the same as in its own pass
    sep = tmp_path / "sep.webm"
    V.make_proxy(c, sep)
    assert proxy.exists() and _dims(proxy) == _dims(sep) == (640, 360)
    assert np.abs(_frame(proxy) - _frame(sep)).mean() < 0.5
    assert not list((tmp_path / "b").rglob("*.tmp.webm")) and not list((tmp_path / "b").rglob("ton.f32"))


def test_chip_path_same_analysis_also_rotated(media, rotated, tmp_path, emul):
    for src in (sorted(media.RAW.glob("VID_*.mp4"))[0], rotated):
        c = _clip(src)
        ref_p = tmp_path / f"ref_{c.hash}.webm"
        ref = V.analyse_clip(c, _dirs(tmp_path / "ref"), proxy=ref_p)
        emul("1")
        hw_p = tmp_path / f"hw_{c.hash}.webm"
        hw = V.analyse_clip(c, _dirs(tmp_path / "hw"), proxy=hw_p, hw=True)
        emul("")
        assert _same(ref, hw) == [], src.name       # analysis frames come in full size → identical results
        assert _dims(hw_p) == _dims(ref_p) == HW.proxy_size(c)
        # same orientation (a wrongly rotated picture would differ by tens of grey levels)
        assert np.abs(_frame(hw_p) - _frame(ref_p)).mean() < 6, src.name


def test_keyframes_only_with_chip(media, tmp_path, emul, monkeypatch):
    c = _clip(sorted(media.RAW.glob("VID_*.mp4"))[1])
    monkeypatch.setattr(V, "KF_ONLY_AB", 1.0)
    ref = V.analyse_clip(c, _dirs(tmp_path / "ref"), proxy=tmp_path / "x.webm")
    assert ref["keyframes_only"] and not (tmp_path / "x.webm").exists()   # long clips: preview made separately
    emul("1")
    hw = V.analyse_clip(c, _dirs(tmp_path / "hw"), hw=True)
    assert _same(ref, hw) == []


def test_decision_rule():
    assert HW.entscheiden(sw_wall=10, sw_cpu=30, hw_wall=5, hw_cpu=3)
    assert HW.entscheiden(sw_wall=10, sw_cpu=30, hw_wall=12, hw_cpu=20)        # a bit slower is fine
    assert HW.entscheiden(sw_wall=10, sw_cpu=30, hw_wall=18, hw_cpu=6)         # much less processor time
    assert not HW.entscheiden(sw_wall=10, sw_cpu=30, hw_wall=18, hw_cpu=25)
    assert not HW.entscheiden(sw_wall=10, sw_cpu=30, hw_wall=25, hw_cpu=2)


def test_slots_and_status(media, emul):
    emul("1")
    c = _clip(sorted(media.RAW.glob("VID_*.mp4"))[0])
    assert HW.status()["stand"] == "bereit"
    ent = HW.pruefen(c)
    assert "hw" in ent and ent.get("faktor")
    st = HW.status()
    assert st["profile"][0]["name"].startswith("H.264")
    if not ent["hw"]:
        return
    with HW.platz(c) as a, HW.platz(c) as b, HW.platz(c) as d:
        assert (a, b, d) == (True, True, False)     # two videos on the chip, the third worker takes the processor


def test_no_chip_status(monkeypatch):
    monkeypatch.delenv("PULSECUT_HWDEC_EMUL", raising=False)
    monkeypatch.setenv("PULSECUT_HWDEC", "0")
    HW.zuruecksetzen()
    assert HW.status() == {"stand": "aus"} and not HW.verfuegbar()
    monkeypatch.delenv("PULSECUT_HWDEC")
    HW.zuruecksetzen()
    assert HW.status()["stand"] in ("kein_geraet", "kein_vaapi", "bereit")
    HW.zuruecksetzen()


def test_failing_chip_falls_back_to_processor(media, tmp_path, emul):
    """The chip fails for every video: everything is analysed on the processor, the format is remembered."""
    from pulsecut.projekt import Job, Projekt
    vid, mus = tmp_path / "v", tmp_path / "m"
    vid.mkdir()
    mus.mkdir()
    for p in sorted(media.RAW.glob("VID_2026071*_1*.mp4"))[:3]:
        shutil.copy2(p, vid / p.name)
    shutil.copy2(media.MUSIK / "01 Morning Groove.mp3", mus)
    emul("fail")
    pr = Projekt.erstellen("Chip", vid, mus, tmp_path / "p")
    pr.boost = True
    pr.analyse_job(Job("analyse"))
    assert len(pr.clips) == 3 and all(c.ana for c in pr.clips)
    assert all((pr.dirs["proxy"] / f"{c.hash}.webm").exists() for c in pr.clips)
    st = HW.status()
    assert st["profile"] and not st["profile"][0]["hw"] and st["profile"][0]["grund"]
    # and with a working chip the same project gives the same analysis
    ref = {c.name: c.ana for c in pr.clips}
    emul("1")
    pr2 = Projekt.erstellen("Chip2", vid, mus, tmp_path / "p2")
    pr2.boost = True
    pr2.analyse_job(Job("analyse"))
    for c in pr2.clips:
        assert _same(ref[c.name], c.ana) == [], c.name


def test_chip_failing_during_the_analysis(media, tmp_path, emul, monkeypatch):
    """The measurement said yes, but a video fails on the chip: it is redone on the processor."""
    from pulsecut.projekt import Job, Projekt
    vid, mus = tmp_path / "v", tmp_path / "m"
    vid.mkdir()
    mus.mkdir()
    for p in sorted(media.RAW.glob("VID_2026071*_1*.mp4"))[:2]:
        shutil.copy2(p, vid / p.name)
    shutil.copy2(media.MUSIK / "01 Morning Groove.mp3", mus)
    emul("fail")
    monkeypatch.setattr(HW, "pruefen", lambda clip: HW._profile().get(HW.profil(clip)) or {"hw": True})
    pr = Projekt.erstellen("Chip", vid, mus, tmp_path / "p")
    pr.analyse_job(Job("analyse"))
    assert len(pr.clips) == 2 and all(c.ana for c in pr.clips)
    assert all((pr.dirs["proxy"] / f"{c.hash}.webm").exists() for c in pr.clips)
    prof = HW.status()["profile"]
    assert len(prof) == 1 and not prof[0]["hw"] and "Impossible" in prof[0]["grund"]
