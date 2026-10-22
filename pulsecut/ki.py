"""KI-Erkennung: eigene Python-Umgebung (einmalig per uv eingerichtet) und Aufträge an den KI-Worker."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .i18n import L as _t
from .util import DATA_HOME, clean_env, log, resource

KI_DIR = DATA_HOME / "ki-umgebung"
KI_ENV_VERSION = "2"
MODELLE = {
    "bild": os.environ.get("PULSECUT_BILD_MODELL", "sentence-transformers/clip-ViT-B-32"),
    "text": os.environ.get("PULSECUT_TEXT_MODELL", "sentence-transformers/clip-ViT-B-32-multilingual-v1"),
    "ton": os.environ.get("PULSECUT_TON_MODELL", "MIT/ast-finetuned-audioset-10-10-0.4593"),
    "sprache": os.environ.get("PULSECUT_WHISPER_MODELL", "small"),
}
_lock = threading.Lock()
_setup_state = {"laeuft": False, "fehler": "", "log": []}


def ki_python():
    env = os.environ.get("PULSECUT_KI_PYTHON")
    if env:
        return Path(env)
    py = KI_DIR / "bin" / "python"
    marker = KI_DIR / ".fertig"
    if py.exists() and marker.exists() and marker.read_text().split()[0] == KI_ENV_VERSION:
        return py
    return None


def status():
    return {"bereit": ki_python() is not None, "laeuft": _setup_state["laeuft"], "fehler": _setup_state["fehler"],
            "log": _setup_state["log"][-12:], "ordner": str(KI_DIR)}


def uv_binary():
    for p in (resource("bin", "uv"), Path(sys.executable).parent / "uv"):
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which("uv")


def _run_logged(cmd, env=None):
    _setup_state["log"].append("$ " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))[:200])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                         stdin=subprocess.DEVNULL)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            _setup_state["log"].append(line[-200:])
            del _setup_state["log"][:-200]
    return p.wait()


def einrichten():
    """Legt die KI-Umgebung an: PyTorch (CPU), sentence-transformers, transformers, faster-whisper (ca. 1,5 GB)."""
    if _setup_state["laeuft"]:
        return False
    _setup_state.update({"laeuft": True, "fehler": "", "log": []})
    try:
        KI_DIR.parent.mkdir(parents=True, exist_ok=True)
        if KI_DIR.exists() and not (KI_DIR / ".fertig").exists():
            shutil.rmtree(KI_DIR, ignore_errors=True)
        uv = uv_binary()
        env = clean_env({"UV_LINK_MODE": "copy", "UV_NO_PROGRESS": "1"})
        py = KI_DIR / "bin" / "python"
        if uv:
            if not py.exists():
                if _run_logged([uv, "venv", "--python", ">=3.10,<3.14", str(KI_DIR)], env):
                    raise RuntimeError(_t("Python-Umgebung konnte nicht angelegt werden"))
            pip = [uv, "pip", "install", "--python", str(py)]
        else:
            if not py.exists():
                base = shutil.which("python3") or "python3"
                if _run_logged([base, "-m", "venv", str(KI_DIR)], env):
                    raise RuntimeError(_t("Python-Umgebung konnte nicht angelegt werden (sudo apt install python3-venv)"))
            pip = [str(py), "-m", "pip", "install", "--disable-pip-version-check"]
        if _run_logged(pip + ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"], env):
            raise RuntimeError(_t("PyTorch konnte nicht installiert werden (Internetverbindung?)"))
        if _run_logged(pip + ["sentence-transformers>=3", "transformers>=4.40", "pillow", "numpy",
                              "faster-whisper>=1.0"], env):
            raise RuntimeError(_t("KI-Pakete konnten nicht installiert werden"))
        chk = subprocess.run([str(py), "-c", "import torch, transformers, sentence_transformers, faster_whisper, PIL"],
                             capture_output=True, text=True, env=clean_env())
        if chk.returncode:
            raise RuntimeError(_t("KI-Umgebung startet nicht: ") + chk.stderr.strip()[-300:])
        (KI_DIR / ".fertig").write_text(f"{KI_ENV_VERSION} {time.strftime('%Y-%m-%d %H:%M')}")
        _setup_state["log"].append(_t("✔ KI-Erkennung eingerichtet"))
        return True
    except Exception as e:
        _setup_state["fehler"] = str(e)
        return False
    finally:
        _setup_state["laeuft"] = False


def run_worker(aufgaben, workdir, progress=None):
    """Führt Aufträge im KI-Worker aus. progress(a, b, text)."""
    py = ki_python()
    if py is None:
        raise RuntimeError(_t("KI-Erkennung ist nicht eingerichtet"))
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    jf = workdir / f"ki_auftrag_{os.getpid()}_{int(time.time() * 1000)}.json"
    jf.write_text(json.dumps({"aufgaben": aufgaben, "modelle": MODELLE}), encoding="utf-8")
    env = clean_env({"TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONNOUSERSITE": "1"})
    worker = os.environ.get("PULSECUT_FAKE_WORKER") or resource("ki_worker.py")   # Tests: simulierte KI
    with _lock:
        p = subprocess.Popen([str(py), "-I", str(worker), str(jf)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env, stdin=subprocess.DEVNULL)
        err = []

        def read_err():
            for line in p.stderr:
                err.append(line.rstrip())
                del err[:-40]

        th = threading.Thread(target=read_err, daemon=True)
        th.start()
        for line in p.stdout:
            line = line.strip()
            if line.startswith("FORTSCHRITT") and progress:
                _, a, b = line.split()
                progress(int(a), int(b), "")
            elif line.startswith("MODELL") and progress:
                progress(None, None, _t("lade KI-Modell {m} (beim ersten Mal Download)", m=line[7:]))
        p.wait()
        th.join(timeout=2)
    jf.unlink(missing_ok=True)
    if p.returncode != 0:
        tail = [e for e in err if e.strip()][-6:]
        raise RuntimeError(_t("KI-Worker abgebrochen: ") + " | ".join(tail)[-600:])


def bild_merkmale(clips, emb_dir, bilder_dir, workdir, progress=None):
    """Bild-Merkmale für alle Clips ohne gespeicherte Merkmale."""
    todo = [c for c in clips if c.ana and c.ana.get("ki_frames") and not (Path(emb_dir) / f"{c.hash}.npy").exists()]
    if not todo:
        return 0
    items = [{"key": c.key, "frames": [str(Path(bilder_dir) / c.hash / f[1]) for f in c.ana["ki_frames"]],
              "out": str(Path(emb_dir) / f"{c.hash}.npy")} for c in todo]
    run_worker([{"art": "bilder", "items": items}], workdir, progress)
    return len(todo)


def ton_merkmale(clips, cache, workdir, progress=None):
    todo = [c for c in clips if c.has_audio and c.key not in cache]
    if not todo:
        return 0
    out = Path(workdir) / "ton_ergebnis.jsonl"
    out.unlink(missing_ok=True)
    run_worker([{"art": "ton", "items": [{"key": c.key, "pfad": str(c.path)} for c in todo], "out": str(out)}],
               workdir, progress)
    for line in out.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            cache[d["key"]] = d["ton"]
        except (json.JSONDecodeError, KeyError):
            pass
    return len(todo)


def text_merkmale(texte, cache, workdir):
    """Text-Merkmale (zwischengespeichert je Text)."""
    need = [t for t in dict.fromkeys(texte) if t not in cache]
    if need:
        out = Path(workdir) / f"texte_{int(time.time() * 1000)}.npy"
        run_worker([{"art": "texte", "texte": need, "out": str(out)}], workdir)
        E = np.load(out)
        out.unlink(missing_ok=True)
        for t, e in zip(need, E):
            cache[t] = [round(float(x), 5) for x in e]
    return np.array([cache[t] for t in texte], np.float32) if texte else np.zeros((0, 512), np.float32)


def transkribieren(pfad, workdir, progress=None, sprache="de"):
    out = Path(workdir) / "sprache.txt"
    out.unlink(missing_ok=True)
    run_worker([{"art": "sprache", "pfad": str(pfad), "out": str(out), "sprache": sprache}], workdir, progress)
    return out.read_text(encoding="utf-8").strip()
