"""Real AI environment and models: setup with uv, CLIP image/text features (German and English), AST sound tags,
Whisper speech input, and the whole recognition on the synthetic project.

Runs only when asked for (downloads ~1.5 GB the first time):

    PULSECUT_KI_TEST=1 PULSECUT_TEST_REAL_HOME=1 python3 -m pytest -m ki tests/test_ki.py -v -s
"""
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pulsecut import ki as KI

pytestmark = [pytest.mark.ki, pytest.mark.slow,
              pytest.mark.skipif(not os.environ.get("PULSECUT_KI_TEST"), reason="set PULSECUT_KI_TEST=1")]

# word on the picture → German and English description of the same thing
SCENES = [("BIRTHDAY CAKE", "Geburtstag mit Torte und Kerzen", "a birthday with a cake and candles"),
          ("SWIMMING POOL", "Kinder schwimmen im Schwimmbad", "children swimming in a pool"),
          ("FIREWORKS", "Feuerwerk am Nachthimmel", "fireworks in the night sky"),
          ("SCHOOL BUS", "Fahrt mit dem Reisebus", "a trip on a bus"),
          ("PIANO CONCERT", "Ein Konzert auf der Bühne", "a concert on a stage"),
          ("SOCCER", "Fußball spielen auf der Wiese", "playing football on a lawn")]


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


@pytest.fixture(scope="module")
def ki_ready():
    if KI.ki_python() is None:
        ok = KI.einrichten()
        st = KI.status()
        assert ok, st["fehler"] + "\n" + "\n".join(st["log"][-40:])
    assert KI.status()["bereit"]
    return KI.ki_python()


def test_setup(ki_ready):
    r = subprocess.run([str(ki_ready), "-c", "import torch, sentence_transformers, transformers, faster_whisper; "
                        "print(torch.__version__, torch.cuda.is_available())"], capture_output=True, text=True)
    print(r.stdout, r.stderr[-500:])
    assert r.returncode == 0


def test_clip_matches_pictures_with_german_and_english(ki_ready, tmp_path):
    font = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                             "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf") if Path(f).exists()), None)
    if not font:
        pytest.skip("DejaVu font missing")
    items = []
    for i, (word, _, _) in enumerate(SCENES):
        f = tmp_path / f"f_{i}.jpg"
        ff("-f", "lavfi", "-i", "color=c=white:s=448x448:d=1", "-vf",
           f"drawtext=fontfile={font}:text='{word}':fontsize=44:fontcolor=black:x=(w-tw)/2:y=(h-th)/2",
           "-frames:v", "1", f)
        items.append({"key": word, "frames": [str(f)], "out": str(tmp_path / f"e_{i}.npy")})
    KI.run_worker([{"art": "bilder", "items": items}], tmp_path)
    E = np.stack([np.load(it["out"]).astype(np.float32)[0] for it in items])
    assert E.shape == (len(SCENES), 512)
    for col, lang in ((1, "de"), (2, "en")):
        T = KI.text_merkmale([s[col] for s in SCENES], {}, tmp_path)
        hits = int(np.sum(np.argmax(E @ T.T, axis=1) == np.arange(len(SCENES))))
        print(lang, "matches", hits, "of", len(SCENES))
        assert hits >= len(SCENES) - 2, f"{lang}: only {hits} of {len(SCENES)} pictures matched"


def test_sound_tags(ki_ready, tmp_path):
    music = tmp_path / "music.wav"
    noise = tmp_path / "applause.wav"
    ff("-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*(262*pow(2,floor(mod(t*2,8))/12))*t)'+"
       "'0.2*sin(2*PI*(392*pow(2,floor(mod(t*2,8))/12))*t)':s=16000:d=12", music)
    ff("-f", "lavfi", "-i", "aevalsrc='0.6*(random(0)*2-1)*pow(abs(sin(PI*t*9.3+3*sin(t*5.1))),12)+"
       "0.5*(random(1)*2-1)*pow(abs(sin(PI*t*7.1+2*sin(t*3.3))),12)':s=16000:d=12", noise)
    cache = {}
    clips = [SimpleNamespace(key=k, path=p, has_audio=True) for k, p in (("music", music), ("noise", noise))]
    assert KI.ton_merkmale(clips, cache, tmp_path) == 2
    m, n = cache["music"], cache["noise"]
    print("music:", {k: max(v) for k, v in m.items() if isinstance(v, list) and k != "t"})
    print("noise:", {k: max(v) for k, v in n.items() if isinstance(v, list) and k != "t"})
    assert max(m["musik"]) > max(n["musik"])
    assert max(m["musik"]) > 0.3


@pytest.mark.parametrize("lang,text,words", [
    ("de", "Am Anfang kommen alle mit dem Bus an. Danach gibt es ein großes Konzert.", ["bus", "konzert"]),
    ("en", "First everyone arrives by bus. After that there is a big concert.", ["bus", "concert"])])
def test_speech_input(ki_ready, tmp_path, lang, text, words):
    if not shutil.which("espeak-ng"):
        pytest.skip("espeak-ng missing")
    wav = tmp_path / f"speech_{lang}.wav"
    subprocess.run(["espeak-ng", "-v", lang, "-s", "140", "-w", str(wav), text], check=True)
    webm = tmp_path / f"speech_{lang}.webm"
    ff("-i", wav, "-c:a", "libopus", webm)   # the browser sends WebM/Opus
    out = KI.transkribieren(webm, tmp_path, sprache=lang).lower()
    print(lang, "→", out)
    assert all(w in out for w in words), out


def test_recognition_on_project(ki_ready, projekt):
    from conftest import prepare
    from pulsecut.projekt import Job
    prepare(projekt)
    for f in projekt.dirs["emb"].glob("*.npy"):   # throw away the simulated features
        f.unlink()
    projekt.cache["texte"] = {}
    projekt.cache["ton"] = {}
    job = Job("erkennung")
    projekt.erkennung_job(job, mit_ki=True)
    info = projekt.erkennung_info()
    assert info["ki"] and info["szenen"]
    print("groups:", [(g["name"], g["szenen"]) for g in info["gruppen"]], "| questions:",
          [f["label"] for f in info["fragen"]])
    tl = projekt.plan(keep_locked=False)
    assert tl["shots"] and tl["differenz"] == 0
