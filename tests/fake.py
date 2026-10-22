"""Helpers for tests with the synthetic clips (gen_clips.py) and a simulated AI."""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = Path(os.environ.get("PULSECUT_TESTDATA") or HERE / ".data").resolve()
RAW = DATA / "camp" / "raw"
MUSIK = DATA / "camp" / "music"
BEATS = DATA / "beats"
PROJ = DATA / "camp" / "Camp_2026_Pulsecut"

BESCHREIBUNG = """Am Anfang kommen alle mit dem Bus an der Jugendherberge an, dann gibt es die Anmeldung mit Anwesenheitsliste und Armbändern.
Danach Kennenlernabend mit Spielen. Jeden Tag sind Proben in Registern und im großen Orchester, zwischendurch Freizeit mit Fußball und Tischtennis.
Am Mittwoch Ausflug ins Museum, das ist ein futuristisches Gebäude. Am letzten Tag Registerproben mit den jungen Dirigentinnen, dann das Abschlusskonzert, danach Gruppenfoto und zum Schluss die Abreise mit dem Bus."""

DESCRIPTION_EN = """First everyone arrives by bus at the youth hostel, then registration with attendance list and wristbands.
After that a get-to-know evening with games. Every day there are rehearsals in sections and full orchestra, in between free time with football and table tennis.
On Wednesday a trip to the museum, a futuristic building. On the last day sectional rehearsals with the young conductors, then the final concert, after that the group photo and finally departure by bus."""

# label prefix in the synthetic clips → index of the keyword parsed from BESCHREIBUNG (-1 = not described: disco)
MAP = [("REGISTERPROBE", 6), ("ANREISE", 0), ("ANMELDUNG", 1), ("ARMBAND", 1), ("KENNENLERN", 2), ("PROBE", 3),
       ("AUSFLUG", 5), ("MUSEUM", 5), ("KONZERT", 7), ("GRUPPENFOTO", 8), ("ABREISE", 9), ("DISCO", -1), ("FREIZEIT", 4)]


def ensure_media():
    """Generates the synthetic footage and music once (a few minutes); later runs reuse it."""
    if not (RAW / "VID_20260716_153200.mp4").exists() or not (MUSIK / "03 Swing Finale.mp3").exists():
        subprocess.run([sys.executable, str(HERE / "gen_clips.py"), str(RAW), str(MUSIK)], check=True)
    if not (BEATS / "truth.json").exists():
        BEATS.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(HERE / "gen_music.py"), str(BEATS)], check=True)


def labels():
    import gen_clips
    return gen_clips.labels()


def true_kw(label):
    for p, k in MAP:
        if label.upper().startswith(p) or p in label.upper():
            return k
    return 4


def fake_ki(pr, seed=3):
    """Writes simulated image and text features into the project cache (as if the AI had looked at the clips)."""
    from pulsecut import erkennung as ER
    rng = np.random.default_rng(seed)
    kws = pr.d["stichworte"]
    texts = [ER.kw_text(k) for k in kws] + ER.voc_texts()
    V = rng.normal(size=(len(texts), 512)).astype(np.float32)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    for t, v in zip(texts, V):
        pr.cache["texte"][t] = v.tolist()
    disco = len(kws) + [v[0] for v in ER.VOKABULAR].index("party")
    lab = labels()
    for c in pr.clips:
        k = true_kw(lab[c.name])
        base = V[disco] if k == -1 else V[k]
        n = len(c.ana["ki_frames"])
        E = base[None, :] * 0.32 + rng.normal(size=(n, 512)).astype(np.float32) * 0.03
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        np.save(pr.dirs["emb"] / f"{c.hash}.npy", E.astype(np.float16))
    return lab
