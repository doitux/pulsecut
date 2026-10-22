"""Synthetic music with known beats and downbeats (ground truth in truth.json) for the beat tracker tests.

    python3 tests/gen_music.py OUT_DIR"""
import json
import subprocess
import sys

import numpy as np

out_dir = sys.argv[1]
sr = 44100
rng = np.random.default_rng(1)


def synth(dur, bpm0, bpm1, meter, intro, kick_beats, swing=0.0, chords=(0, 5, 7, 3), end_hit=False):
    # Beatzeiten mit Tempoverlauf bpm0 → bpm1
    beats = []
    t = intro
    while t < dur - 3:
        beats.append(t)
        frac = t / dur
        bpm = bpm0 + (bpm1 - bpm0) * frac
        t += 60.0 / bpm
    beats = np.array(beats)
    y = np.zeros(int(sr * dur), np.float32)

    def add(t0, sig, gain):
        i = int(t0 * sr)
        if i >= len(y):
            return
        n = min(len(sig), len(y) - i)
        y[i:i + n] += gain * sig[:n]

    tk = np.arange(int(0.25 * sr)) / sr
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 12)
    tsn = np.arange(int(0.18 * sr)) / sr
    snare = rng.standard_normal(len(tsn)) * np.exp(-tsn * 25) * 0.6 + np.sin(2 * np.pi * 190 * tsn) * np.exp(-tsn * 30) * 0.4
    th = np.arange(int(0.05 * sr)) / sr
    hat = rng.standard_normal(len(th)) * np.exp(-th * 90)
    hat = np.diff(np.r_[0, hat])
    base = 110.0
    for i, b in enumerate(beats):
        pos = i % meter
        bar = i // meter
        nxt = beats[i + 1] if i + 1 < len(beats) else b + 0.5
        if pos in kick_beats:
            add(b, kick, 0.9 if pos == 0 else 0.55)
        if meter == 4 and pos in (1, 3):
            add(b, snare, 0.35)
        if meter == 3 and pos in (1, 2):
            add(b, snare, 0.2)
        add(b, hat, 0.12)
        add(b + (nxt - b) * (0.5 + swing), hat, 0.08)
        if pos == 0:   # Akkordwechsel auf der Eins (Pad + Bass)
            root = base * 2 ** (chords[bar % len(chords)] / 12)
            blen = (beats[min(i + meter, len(beats) - 1)] - b) if i + meter < len(beats) else 2.0
            tt = np.arange(int(blen * sr)) / sr
            env = np.minimum(1, tt / 0.03) * np.exp(-tt * 0.8)
            pad = sum(np.sin(2 * np.pi * root * r * 2 * tt) for r in (1, 1.26, 1.5)) * env * 0.08
            bass = np.sin(2 * np.pi * root / 2 * tt) * np.exp(-tt * 2) * 0.25
            add(b, (pad + bass).astype(np.float32), 1.0)
    if end_hit:
        last = beats[-1] + 60 / bpm1
        tt = np.arange(int(3.0 * sr)) / sr
        add(last, (kick[:len(tt)] if len(kick) >= len(tt) else np.pad(kick, (0, len(tt) - len(kick)))) * 1.0, 1.0)
        add(last, (sum(np.sin(2 * np.pi * base * r * tt) for r in (1, 1.26, 1.5, 2)) * np.exp(-tt * 1.2) * 0.2).astype(np.float32), 1.0)
    y /= np.abs(y).max() * 1.1
    downs = [float(b) for i, b in enumerate(beats) if i % meter == 0]
    return y, {"beats": beats.tolist(), "downs": downs, "meter": meter}


tracks = [("tempo_drift_96-100.wav", synth(221, 96, 100, 4, 1.7, (0, 2), swing=0.0)),
          ("swing_132.mp3", synth(130, 132, 132, 4, 0.4, (0,), swing=0.17, chords=(0, 3, 5, 7), end_hit=True))]
truth = {}
for name, (y, gt) in tracks:
    st = np.stack([y, y], axis=1)
    p = f"{out_dir}/{name}"
    pcm = (st * 32767).astype("<i2").tobytes()
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", "-"]
    args += (["-c:a", "pcm_s16le"] if name.endswith(".wav") else ["-c:a", "libmp3lame", "-b:a", "192k"]) + [p]
    subprocess.run(args, input=pcm, check=True)
    truth[name] = gt
    print("ok", name, len(gt["beats"]), "Beats")
# Walzer (3/4) für den Taktart-Test
y, gt = synth(60, 150, 150, 3, 0.5, (0,), chords=(0, 7, 5))
pcm = (np.stack([y, y], 1) * 32767).astype("<i2").tobytes()
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", "-", f"{out_dir}/walzer.wav"],
               input=pcm, check=True)
truth["walzer.wav"] = gt
with open(f"{out_dir}/truth.json", "w") as f:
    json.dump(truth, f)
