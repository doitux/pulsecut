"""Hardware-Dekodierung der Videos über den Grafikchip (VAAPI, z. B. Intel-Onboard-Grafik).

Der Dekodier-Baustein im Chip nimmt dem Prozessor die meiste Arbeit der Video-Analyse ab. Ob er für ein Videoformat
(Codec, Bittiefe, Auflösung) funktioniert und schneller ist, wird beim ersten Video dieses Formats einmal gemessen
und gemerkt (Einstellungsdatei, je Grafikchip). Klappt etwas nicht, läuft das Video auf dem Prozessor – das Ergebnis
der Analyse ist in beiden Fällen dasselbe: die Bilder für die Analyse werden in voller Größe vom Chip geholt und wie
bisher auf dem Prozessor verkleinert, nur die Vorschau-Videos verkleinert der Chip selbst.

PULSECUT_HWDEC=0 schaltet die Hardware-Dekodierung ab, =1 nutzt sie ohne Messung, wo sie funktioniert.
PULSECUT_HWDEC_EMUL=1 (nur für Tests) spielt den Weg über den Chip mit reinen Software-Filtern nach, =fail lässt ihn
scheitern.
"""
import contextlib
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .i18n import L as _t
from .util import CONFIG_HOME, atomic_write_json, clean_env, log, read_json

SLOTS = 2               # so viele Videos gleichzeitig über den Chip, die übrigen Arbeiter nehmen den Prozessor
TEST_SEK = 4.0          # Länge des Messausschnitts
SCHNELL_GENUG = 1.3     # Chip wird genommen, wenn er höchstens so viel langsamer ist (er entlastet den Prozessor) …
CPU_ERSPARNIS = 0.5     # … oder höchstens diesen Anteil der Prozessorzeit braucht (und nicht doppelt so lange dauert)

_lock = threading.Lock()
_profil_locks = {}
_slots = threading.Semaphore(SLOTS)
_state = {"geraet": None, "vaapi": None, "profile": None}


def _modus():
    v = (os.environ.get("PULSECUT_HWDEC") or "auto").strip().lower()
    if v in ("0", "aus", "off", "no", "nein", "false"):
        return "aus"
    if v in ("1", "an", "on", "yes", "ja", "true"):
        return "an"
    return "auto"


def _emul():
    return (os.environ.get("PULSECUT_HWDEC_EMUL") or "").strip().lower()


def _sysfs(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return ""


def geraet():
    """(Render-Knoten, Kennung, Anzeigename) des ersten Grafikchips oder None."""
    if _state["geraet"] is None:
        res = False
        if _emul():
            res = ("emul", "emul", "Emulation")
        else:
            for node in sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []:
                if not os.access(node, os.R_OK | os.W_OK):
                    continue
                dev = Path("/sys/class/drm") / node.name / "device"
                vendor, device = _sysfs(dev / "vendor"), _sysfs(dev / "device")
                try:
                    driver = os.path.basename(os.readlink(dev / "driver"))
                except OSError:
                    driver = ""
                firma = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA"}.get(vendor, vendor or "GPU")
                res = (str(node), f"{vendor}:{device}:{driver}", f"{firma} ({driver})" if driver else firma)
                break
        _state["geraet"] = res
    return _state["geraet"] or None


def ffmpeg_vaapi():
    """Kann das installierte ffmpeg VAAPI (Dekodieren und Verkleinern auf dem Chip)?"""
    if _state["vaapi"] is None:
        if _emul():
            _state["vaapi"] = True
        else:
            try:
                a = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"], capture_output=True, text=True,
                                   env=clean_env(), stdin=subprocess.DEVNULL, timeout=20).stdout
                f = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                                   env=clean_env(), stdin=subprocess.DEVNULL, timeout=20).stdout
                _state["vaapi"] = "vaapi" in a.split() and "scale_vaapi" in f and "hwdownload" in f
            except (OSError, subprocess.SubprocessError):
                _state["vaapi"] = False
    return _state["vaapi"]


def verfuegbar():
    return _modus() != "aus" and geraet() is not None and ffmpeg_vaapi()


# ───────────────────────────────────────────── ffmpeg-Bausteine

def eingang(hw):
    """Eingangs-Optionen (vor -i). Mit Chip: keine automatische Drehung – die macht dann rot_filter()."""
    if not hw:
        return []
    if _emul():
        return ["-noautorotate"]
    return ["-hwaccel", "vaapi", "-hwaccel_device", geraet()[0], "-hwaccel_output_format", "vaapi",
            "-noautorotate"]


def rot_theta(rot):
    """ffprobe-Drehung (Anzeigematrix, z. B. -90 beim Hochkant-Handyvideo) → Drehung im Uhrzeigersinn."""
    return int(round(-(rot or 0))) % 360


def rot_filter(rot):
    th = rot_theta(rot)
    return {90: "transpose=clock", 180: "hflip,vflip", 270: "transpose=cclock"}.get(th, "")


def _kette(*teile):
    return ",".join(t for t in teile if t)


def _sw_format(pix):
    return "p010le" if pix and ("10" in pix or "12" in pix) else "nv12"


def herunterladen(rot, pix=""):
    """Bilder vom Chip in den Arbeitsspeicher (volle Größe, dann gedreht wie das Video angezeigt wird)."""
    if _emul() == "fail":
        return _kette("hwdownload,format=nv12", rot_filter(rot))
    if _emul():
        return _kette("format=nv12", rot_filter(rot))
    return _kette(f"hwdownload,format={_sw_format(pix)}", rot_filter(rot))


def verkleinern(w, h, rot):
    """Auf dem Chip auf w×h (Anzeige-Größe nach der Drehung) verkleinern, holen, drehen."""
    if rot_theta(rot) in (90, 270):
        cw, ch = h, w
    else:
        cw, ch = w, h
    if _emul() == "fail":
        return _kette(f"scale_vaapi=w={cw}:h={ch}", "hwdownload,format=nv12", rot_filter(rot))
    if _emul():
        return _kette(f"scale={cw}:{ch}:flags=bilinear", "format=nv12", rot_filter(rot))
    return _kette(f"scale_vaapi=w={cw}:h={ch}", "hwdownload,format=nv12", rot_filter(rot))


def proxy_size(clip):
    """Größe der Vorschau-Videos (kurze Seite 360, gerade Zahlen) – wie scale=-2:360 bzw. 360:-2."""
    if clip.w >= clip.h:
        return max(2, int(round(360 * clip.w / max(1, clip.h) / 2)) * 2), 360
    return 360, max(2, int(round(360 * clip.h / max(1, clip.w) / 2)) * 2)


# ───────────────────────────────────────────── Messung und Entscheidung

def profil(clip):
    """Videoformat, für das einmal gemessen wird."""
    groesse = "4k" if max(clip.w, clip.h) > 2200 else ("hd" if max(clip.w, clip.h) > 1000 else "sd")
    return f"{clip.codec or '?'}|{clip.pix or '?'}|{groesse}"


def _settings_file():
    return CONFIG_HOME / "einstellungen.json"


def _profile():
    if _state["profile"] is None:
        d = (read_json(_settings_file(), {}) or {}).get("hwdec") or {}
        g = geraet()
        prof = dict(d.get("profile") or {}) if g and d.get("geraet") == g[1] and not _emul() else {}
        # Was an Treiber oder Fehlern scheiterte, wird beim nächsten Programmstart neu geprüft (vielleicht ist der
        # Treiber inzwischen installiert); „nicht unterstützt“ und „Prozessor schneller“ bleiben gemerkt.
        _state["profile"] = {k: v for k, v in prof.items() if v.get("hw") or v.get("grund") in ("codec", "langsamer")}
    return _state["profile"]


def _speichern():
    if _emul():
        return
    try:
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        d = read_json(_settings_file(), {}) or {}
        d["hwdec"] = {"geraet": geraet()[1], "profile": _profile()}
        atomic_write_json(_settings_file(), d)
    except OSError:
        pass


def _messen(cmd):
    """(ok, Sekunden, Prozessorsekunden, Fehlertext) für einen ffmpeg-Lauf."""
    t0 = time.monotonic()
    try:
        p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, env=clean_env())
    except OSError as e:
        return False, 0.0, 0.0, str(e)
    err = p.stderr.read().decode("utf-8", "replace")
    _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    wall = time.monotonic() - t0
    return p.returncode == 0, wall, ru.ru_utime + ru.ru_stime, err.strip()


def _testbefehl(clip, hw):
    from .util import ffmpeg_cmd
    pw, ph = proxy_size(clip)
    if hw:
        g = (f"[0:v]split=2[p][x];[p]{verkleinern(pw, ph, clip.rot)}[pv];"
             f"[x]fps=4,{herunterladen(clip.rot, clip.pix)}[xv]")
    else:
        g = f"[0:v]split=2[p][x];[p]scale={pw}:{ph}:flags=bilinear[pv];[x]fps=4,format=nv12[xv]"
    return (ffmpeg_cmd() + eingang(hw) + ["-t", str(TEST_SEK), "-i", str(clip.path), "-filter_complex", g,
                                          "-map", "[pv]", "-f", "null", "-", "-map", "[xv]", "-f", "null", "-"])


def _grund(err):
    """Warum der Chip nicht geht – als Kennung (übersetzt wird erst bei der Anzeige)."""
    e = err.lower()
    if "vainitialize" in e or "failed to initialise vaapi" in e or ("libva" in e and "driver" in e):
        return "treiber"
    if any(x in e for x in ("no support for codec", "not supported", "unsupported", "no hw config",
                            "failed setup for format", "hwaccel initialisation returned error")):
        return "codec"
    lines = [re.sub(r"^\[[^\]]*\]\s*", "", ln).strip() for ln in err.strip().splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("Nothing was written")] or ["?"]
    return "fehler:" + lines[0][:100]


def grund_text(g):
    if g == "treiber":
        return _t("VAAPI-Treiber fehlt (Paket intel-media-va-driver oder i965-va-driver)")
    if g == "codec":
        return _t("vom Grafikchip nicht unterstützt")
    if g == "langsamer":
        return _t("Prozessor ist schneller")
    if g.startswith("fehler:"):
        return _t("funktioniert nicht: {err}", err=g[7:])
    return g


CODEC_NAME = {"h264": "H.264", "hevc": "HEVC", "vp9": "VP9", "vp8": "VP8", "av1": "AV1", "mpeg2video": "MPEG-2",
              "mpeg4": "MPEG-4", "mjpeg": "MJPEG", "vc1": "VC-1"}


def format_name(key):
    codec, pix, groesse = (key.split("|") + ["", "", ""])[:3]
    n = CODEC_NAME.get(codec, codec.upper())
    if "10" in pix or "12" in pix:
        n += " " + _t("10 Bit")
    if groesse == "4k":
        n += " 4K"
    return n


def entscheiden(sw_wall, sw_cpu, hw_wall, hw_cpu):
    """Chip nehmen? Er entlastet den Prozessor, darf also etwas langsamer sein."""
    if hw_wall <= sw_wall * SCHNELL_GENUG:
        return True
    return hw_cpu <= sw_cpu * CPU_ERSPARNIS and hw_wall <= sw_wall * 2


def pruefen(clip):
    """Einmal je Videoformat: Funktioniert der Chip, und lohnt er sich? Ergebnis wird gemerkt."""
    key = profil(clip)
    with _lock:
        ent = _profile().get(key)
        if ent is not None:
            return ent
        plock = _profil_locks.setdefault(key, threading.Lock())
    with plock:
        with _lock:
            ent = _profile().get(key)
        if ent is not None:
            return ent
        ok, hw_wall, hw_cpu, err = _messen(_testbefehl(clip, True))
        if not ok:
            ent = {"hw": False, "grund": _grund(err)}
        elif _modus() == "an":
            ent = {"hw": True, "faktor": None}
        else:
            ok2, sw_wall, sw_cpu, _ = _messen(_testbefehl(clip, False))
            if not ok2:
                ent = {"hw": True, "faktor": None}
            else:
                ent = {"hw": entscheiden(sw_wall, sw_cpu, hw_wall, hw_cpu),
                       "faktor": round(sw_wall / max(hw_wall, 1e-3), 2),
                       "cpu": round(hw_cpu / max(sw_cpu, 1e-3), 2)}
                if not ent["hw"]:
                    ent["grund"] = "langsamer"
        ent["codec"] = clip.codec or "?"
        ent["zeit"] = time.strftime("%Y-%m-%d")
        with _lock:
            _profile()[key] = ent
            _speichern()
        if ent["hw"]:
            log("  " + _t("Grafikchip dekodiert {codec} ({x}× so schnell wie der Prozessor)",
                          codec=format_name(key), x=ent.get("faktor") or "?"))
        else:
            log("  " + _t("{codec}: Dekodierung auf dem Prozessor – {grund}", codec=format_name(key),
                          grund=grund_text(ent.get("grund", ""))))
        return ent


def fehlgeschlagen(clip, err):
    """Ein Video ist über den Chip gescheitert: dieses Format künftig auf dem Prozessor."""
    key = profil(clip)
    with _lock:
        text = str(err).split("\n", 1)[-1]      # ohne die Zeile „Befehl fehlgeschlagen: …“
        _profile()[key] = {"hw": False, "grund": _grund(text), "codec": clip.codec or "?",
                           "zeit": time.strftime("%Y-%m-%d")}
        _speichern()


@contextlib.contextmanager
def platz(clip):
    """True, wenn dieses Video jetzt über den Chip laufen soll (Format geeignet und ein Platz frei)."""
    if not verfuegbar() or not getattr(clip, "codec", None):
        yield False
        return
    if not pruefen(clip).get("hw"):
        yield False
        return
    if not _slots.acquire(blocking=False):
        yield False
        return
    try:
        yield True
    finally:
        _slots.release()


def status():
    """Für die Oberfläche: Ist der Chip im Einsatz, für welche Formate, und wenn nicht, warum nicht?"""
    if _modus() == "aus":
        return {"stand": "aus"}
    g = geraet()
    if g is None:
        return {"stand": "kein_geraet"}
    if not ffmpeg_vaapi():
        return {"stand": "kein_vaapi", "geraet": g[2]}
    with _lock:
        prof = [{"format": k, "name": format_name(k), "hw": bool(v.get("hw")), "faktor": v.get("faktor"),
                 "grund": grund_text(v.get("grund", "")) if not v.get("hw") else ""}
                for k, v in sorted(_profile().items())]
    return {"stand": "bereit", "geraet": g[2], "profile": prof}


def zuruecksetzen():
    """Nur für Tests: Zustand vergessen."""
    _state.update(geraet=None, vaapi=None, profile=None)
    _profil_locks.clear()
