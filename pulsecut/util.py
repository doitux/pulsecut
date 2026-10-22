"""Hilfsfunktionen: Prozesse, Zeitcodes, Protokoll, Pfade, Schriften, PNG."""
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

FPS = 25

CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pulsecut"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "pulsecut"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pulsecut"


def _migrate_old_dirs():
    """Ordner von Taktschnitt 1.0 (dem früheren Namen) übernehmen, z. B. die eingerichtete KI-Umgebung."""
    for new in (CACHE_HOME, DATA_HOME, CONFIG_HOME):
        old = new.with_name("taktschnitt")
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass


_migrate_old_dirs()

_print_lock = threading.Lock()
_local = threading.local()


def resource(*parts):
    """Pfad zu mitgelieferten Dateien (auch im gepackten Programm)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base.joinpath("pulsecut", *parts)
    if p.exists():
        return p
    return Path(__file__).resolve().parent.joinpath(*parts)


def set_log_target(fn):
    _local.target = fn


def log(msg=""):
    fn = getattr(_local, "target", None)
    with _print_lock:
        print(msg, flush=True)
    if fn:
        try:
            fn(str(msg))
        except Exception:
            pass


def clean_env(extra=None):
    """Umgebung für externe Programme (ffmpeg, melt, KI): ohne die Bibliothekspfade des gepackten Programms."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for k in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH",
                  "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH",
                  "QT_QPA_PLATFORM_PLUGIN_PATH", "SSL_CERT_FILE", "GDK_PIXBUF_MODULE_FILE"):
            orig = env.pop(k + "_ORIG", None)
            env.pop(k, None)
            if orig:
                env[k] = orig
    if extra:
        env.update(extra)
    return env


def run(cmd, check=True, binary=False, input=None, timeout=None):
    res = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL if input is None else None, input=input, timeout=timeout,
                         env=clean_env())
    if check and res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace") if res.stderr else ""
        from .i18n import L as _t
        raise RuntimeError(_t("Befehl fehlgeschlagen: {cmd} …", cmd=" ".join(map(str, cmd[:6]))) + "\n" + err[-1500:])
    if binary:
        return res.stdout
    return res.stdout.decode("utf-8", "replace") if res.stdout is not None else ""


def ffmpeg_cmd():
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]


def tools_status():
    """Welche externen Programme sind da?"""
    st = {t: bool(shutil.which(t)) for t in ("ffmpeg", "ffprobe", "melt")}
    st["vpx"] = False
    if st["ffmpeg"]:
        enc = run(["ffmpeg", "-hide_banner", "-encoders"], check=False)
        st["vpx"] = "libvpx" in enc
        st["opus"] = "libopus" in enc
        st["x264"] = "libx264" in enc
    return st


def tc(frames, fps=FPS):
    """Frames → MLT-Zeitcode HH:MM:SS.mmm."""
    ms = int(round(frames * 1000 / fps))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def fmt_dur(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def smoothstep(x, a, b):
    t = np.clip((np.asarray(x, dtype=np.float64) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def ddist(u, v):
    """Bildabstand zweier Perspektiv-Deskriptoren (0 = gleich, ~0,45 = andere Perspektive)."""
    return float(np.mean(np.abs(np.asarray(u, np.float32) - np.asarray(v, np.float32))))


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def parse_iso(s):
    if not s:
        return None
    s = s.strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:?\d\d)?$", s)
    if not m:
        return None
    base, _frac, tz = m.groups()
    try:
        dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    if dt.year < 2005:
        return None
    if tz:
        tz = tz.replace(":", "")
        off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * (1 if tz[0] == "+" else -1)
        dt = dt.replace(tzinfo=timezone(off))
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def find_font(bold=True):
    try:
        f = run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold" if bold else "DejaVu Sans"], check=False).strip()
        if f and Path(f).exists():
            return f
    except FileNotFoundError:
        pass
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/noto/NotoSans-Bold.ttf"):
        if Path(f).exists():
            return f
    return None


def ff_path(p):
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def write_png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def atomic_write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def r(arr, k=4):
    return [round(float(x), k) for x in arr]


def clamp(x, a, b):
    return max(a, min(b, x))


def lin_db(db):
    return 10 ** (db / 20.0)


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_.-]+", "_", s).strip("_") or "Projekt"


def hypot(a, b):
    return math.hypot(a, b)
