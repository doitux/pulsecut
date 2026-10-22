"""Beat tracker against synthetic music with known beats and downbeats."""
import json

import numpy as np
import pytest

from pulsecut.musik import MusikLayout, analyse_music


@pytest.fixture(scope="module")
def truth(media):
    return json.loads((media.BEATS / "truth.json").read_text())


@pytest.mark.parametrize("name", ["tempo_drift_96-100.wav", "swing_132.mp3", "walzer.wav"])
def test_beats_and_downbeats(media, truth, name):
    gt = truth[name]
    r = analyse_music(media.BEATS / name, {})
    b, gb = np.array(r["beats"]), np.array(gt["beats"])
    err = np.array([np.min(np.abs(b - x)) for x in gb])
    downs = np.array([x for x, d in zip(r["beats"], r["down"]) if d])
    derr = np.array([np.min(np.abs(downs - x)) for x in gt["downs"]])
    assert r["takt"] == gt["meter"]
    assert np.median(err) < 0.03, f"median beat error {np.median(err):.3f} s"
    assert np.mean(derr < 0.05) > 0.9, f"downbeats hit {np.mean(derr < 0.05):.0%}"


def test_corrections(media):
    p = media.BEATS / "swing_132.mp3"
    auto = analyse_music(p, {})
    half = analyse_music(p, {"oktave": -1})
    assert abs(half["bpm"] - auto["bpm"] / 2) < 2
    fixed = analyse_music(p, {"bpm": 66})
    assert abs(fixed["bpm"] - 66) < 1.5


def test_layout_shortening(projekt):
    tracks = projekt.active_tracks()
    full = MusikLayout(tracks, "direkt", 2.0, None, {}, "takt")
    target = full.D - 120
    short = MusikLayout(tracks, "blende", 2.0, target, {1: "hinten"}, "takt")
    assert abs(short.D - target) < 4
    assert len(short.units) > 10
    assert all(b > a for a, b in zip(short.units, short.units[1:]))
