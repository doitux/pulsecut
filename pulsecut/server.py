"""Lokaler HTTP-Server: liefert die Oberfläche und die Schnittstelle zum Projekt (nur 127.0.0.1)."""
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from . import APP_NAME, VERSION, version_text
from . import erkennung as ER
from . import export as EX
from . import hwdec as HW
from . import ki as KI
from . import planer as PL
from .i18n import L as _t, fmt_datetime, get_lang, set_lang
from .projekt import Projekt, recent_projects
from .util import clean_env, resource, tools_status
from .video import BEWEGUNG_LABEL


class AppState:
    def __init__(self):
        self.pr = None
        self.lock = threading.RLock()
        self.tools = tools_status()
        self.qwebchannel_js = None
        self.sprache_text = ""
        self.bridge = False

    def open(self, pr):
        with self.lock:
            self.pr = pr
        pr.start_job("musik", pr.musik_job)
        pr.start_job("analyse", self._analyse_and_restore)

    def _analyse_and_restore(self, job):
        pr = self.pr
        job.text = _t("Videos warten, bis die Musik fertig analysiert ist …")
        for _ in range(1200):   # erst die Musik (schnell), damit Schritt 2 sofort benutzbar ist
            if not pr.jobs["musik"].laeuft:
                break
            time.sleep(0.5)
        pr.analyse_job(job)
        # Erkennung aus dem Zwischenspeicher wiederherstellen (falls schon einmal gemacht)
        for _ in range(60):
            if not pr.jobs["musik"].laeuft:
                break
            time.sleep(0.5)
        if pr.d["stichworte"]:
            try:
                pr.compute_erkennung()
            except Exception:
                traceback.print_exc()


STATE = AppState()


def need_pr():
    if STATE.pr is None:
        raise RuntimeError(_t("Kein Projekt geöffnet"))
    return STATE.pr


DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / "pulsecut.desktop"


def desktop_eintragen():
    """Startmenü-Eintrag für das AppImage anlegen (Plasma/GNOME, ohne Root)."""
    app = os.environ.get("APPIMAGE")
    if not app:
        raise RuntimeError(_t("Nur beim Start als AppImage möglich."))
    icon_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    (icon_dir / "pulsecut.png").write_bytes(resource("ui", "icon.png").read_bytes())
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text("[Desktop Entry]\nType=Application\nName=Pulsecut\n"
                            "GenericName=Cut videos to the beat\nGenericName[de]=Videos auf den Takt schneiden\n"
                            "Comment=Automatically cut recap videos to the beat of the music\n"
                            "Comment[de]=Rückblick-Videos automatisch im Takt der Musik schneiden\n"
                            f"Exec=\"{app}\" %F\n"
                            "Icon=pulsecut\nTerminal=false\nCategories=AudioVideo;Video;AudioVideoEditing;\n"
                            "StartupWMClass=pulsecut\n", encoding="utf-8")
    for cmd in (["update-desktop-database", str(DESKTOP_FILE.parent)], ["kbuildsycoca6"], ["kbuildsycoca5"]):
        try:
            subprocess.run(cmd, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return str(DESKTOP_FILE)


def zustand():
    pr = STATE.pr
    out = {"version": version_text(), "version_nr": VERSION, "app": APP_NAME, "sprache": get_lang(), "werkzeuge": STATE.tools, "ki": KI.status(),
           "zuletzt": recent_projects(), "bridge": STATE.bridge, "projekt": None,
           "appimage": os.environ.get("APPIMAGE"), "desktop": DESKTOP_FILE.exists()}
    if pr:
        out["projekt"] = {"name": pr.d["name"], "ordner": str(pr.ordner), "videos": pr.d["videos"],
                          "musik": pr.d["musik"], "erledigt": pr.d["erledigt"], "jobs": pr.job_status(),
                          "clips": len(pr.clips), "stuecke": len(pr.tracks),
                          "stichworte": len(pr.d["stichworte"]), "erkennung": pr.erk is not None,
                          "timeline": bool(pr.d.get("timeline")), "exporte": pr.d.get("exporte", []),
                          "boost": pr.boost, "hwdec": HW.status(),
                          "sprache_text": STATE.sprache_text}
    return out


def musik_info(pr):
    return {"stuecke": [pr.track_info(i) for i in range(len(pr.tracks))], "layout": pr.layout_info(),
            "uebergang": pr.d["musik_uebergang"], "ziel": pr.d.get("ziel_dauer"),
            "kuerzen": pr.d.get("kuerzen") or {}, "laeuft": pr.jobs["musik"].laeuft}


def videos_info(pr):
    out = []
    for c in pr.clips:
        kf = c.ana.get("ki_frames", []) if c.ana else []
        out.append({"name": c.name, "ordner": c.path.parent.name, "zeit": fmt_datetime(c.start),
                    "quelle": c.time_source, "dauer": round(c.dur, 1), "hoch": c.portrait,
                    "q": round(c.mean_q, 2), "prio": c.prio, "ton": c.ton, "sichten": len(c.segs),
                    "bilder": [f"/bild/{c.hash}/{kf[int(round(i))][1]}" for i in np.linspace(0, len(kf) - 1, min(4, len(kf)))] if kf else [],
                    "gut": round(c.good_sec, 1)})
    return {"clips": out, "sortierung": pr.d.get("sortierung", "zeit"), "laeuft": pr.jobs["analyse"].laeuft,
            "ohne_zeit": sum(1 for c in pr.clips if c.time_source == "Dateidatum")}


def gewichtung_info(pr):
    """Für Schritt 7: Anteile je Stichwort, Material-Hinweise am Regler, Vorschau der Schnitte je Szene."""
    v = pr.anteile_vorschau()
    return {"anteile": {k: round(x, 1) for k, x in v["kw"].items()}, "material": v["material"], "plan": v["szene"],
            "hat_film": bool(pr.d.get("timeline"))}


def api_get(path, q):
    if path == "/api/zustand":
        return zustand()
    pr = need_pr()
    if path == "/api/musik":
        return musik_info(pr)
    if path == "/api/videos":
        return videos_info(pr)
    if path == "/api/stichworte":
        return {"stichworte": pr.d["stichworte"], "beschreibung": pr.d.get("beschreibung", "")}
    if path == "/api/tage":
        return pr.tage_info()
    if path == "/api/erkennung":
        info = pr.erkennung_info()
        return {"erkennung": info, "stichworte": pr.d["stichworte"]}
    if path == "/api/gewichtung":
        info = pr.erkennung_info()
        return dict({"erkennung": info, "stichworte": pr.d["stichworte"], "dauer": pr.layout.D if pr.layout else 0},
                    **gewichtung_info(pr))
    if path == "/api/schnitt":
        L = pr.layout
        ul = L.unit_len() if L else 2.0
        return {"schnitt": pr.d["schnitt"], "k_default": pr.k_default(), "einheit": round(ul, 3),
                "raster": pr.d["schnitt"].get("raster", "takt"), "dauer": round(L.D, 1) if L else 0,
                "taktart": [t["takt"] for t in pr.active_tracks()]}
    if path == "/api/timeline":
        info = pr.timeline_info()
        pr.atmo_plan(info["shots"])
        return info
    if path.startswith("/api/clipbilder/"):
        name = urllib.parse.unquote(path.split("/", 3)[3])
        c = pr.clip_by_name().get(name)
        if not c:
            raise RuntimeError(_t("Clip nicht gefunden"))
        return {"name": c.name, "dauer": c.dur, "hoch": c.portrait, "aspect": c.aspect,
                "bilder": [[f[0], f"/bild/{c.hash}/{f[1]}"] for f in c.ana.get("ki_frames", [])],
                "aus": [list(x) for x in c.excl], "proxy": f"/media/proxy/{c.hash}.webm"}
    if path == "/api/entfernen":
        return pr.entfernen_optionen(q.get("id", [""])[0])
    if path == "/api/szenenclips":
        return pr.szenen_clips(q.get("id", [""])[0])
    if path == "/api/bereich":
        sid = q.get("id", [""])[0]
        tl, _ = pr.relayout()
        sh = next((s for s in tl if s["id"] == sid), None)
        if sh is None:
            raise RuntimeError(_t("Schnitt nicht gefunden"))
        c = pr.clip_by_name()[sh["clip"]]
        rg = PL.slip_range(tl, sh, c, pr.xf())
        others = [{"id": s["id"], "src": s["src"], "dur": s["dur"], "tl": s["tl0"], "lock": bool(s.get("lock"))}
                  for s in tl if s["clip"] == sh["clip"] and s is not sh]
        return {"bereich": rg, "andere": others, "xf": pr.xf(), "gap": PL.GAP}
    if path == "/api/exporte":
        return {"formate": {k: _t(v["label"]) for k, v in EX.FORMATE.items()}, "dateien": pr.d.get("exporte", []),
                "melt": STATE.tools.get("melt")}
    if path == "/api/titelstile":
        from . import titel as TI
        return {"stile": TI.stil_liste(get_lang()), "schriften": TI.schriften(), "aktuell": pr.titelstil()}
    if path == "/api/ls":
        p = Path(q.get("pfad", [str(Path.home())])[0]).expanduser()
        if not p.is_dir():
            p = Path.home()
        dirs = sorted([x.name for x in p.iterdir() if x.is_dir() and not x.name.startswith(".")], key=str.lower)
        nv = sum(1 for x in p.iterdir() if x.is_file() and x.suffix.lower() in {".mp4", ".mov", ".m4v", ".mts", ".3gp", ".mkv", ".avi"})
        na = sum(1 for x in p.iterdir() if x.is_file() and x.suffix.lower() in {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus"})
        return {"pfad": str(p), "eltern": str(p.parent), "ordner": dirs, "videos": nv, "audio": na}
    raise KeyError(path)


def api_post(path, b, raw=None, ctype=""):
    if path == "/api/projekt/neu":
        pr = Projekt.erstellen(b.get("name", ""), b["videos"], b["musik"], b.get("ordner") or None)
        STATE.open(pr)
        return {"ordner": str(pr.ordner)}
    if path == "/api/projekt/oeffnen":
        pr = Projekt(b["ordner"])
        STATE.open(pr)
        return {"ordner": str(pr.ordner)}
    if path == "/api/sprache/oberflaeche":
        return {"sprache": set_lang(str(b.get("sprache", "")))}
    if path == "/api/ki/einrichten":
        threading.Thread(target=KI.einrichten, daemon=True).start()
        return {}
    if path == "/api/desktop":
        return {"datei": desktop_eintragen()}
    if path == "/api/oeffnen":
        p = Path(b["pfad"])
        if p.exists():
            subprocess.Popen(["xdg-open", str(p)], env=clean_env(), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return {}
    pr = need_pr()
    if path == "/api/musik/fix":
        pr.set_music_fix(int(b["i"]), str(b.get("aktion", "")), b.get("wert"))
        return musik_info(pr)
    if path == "/api/musik/stuecke":
        pr.set_music_order(b.get("reihenfolge", []), b.get("aktiv", {}))
        return musik_info(pr)
    if path == "/api/musik/einstellungen":
        if "art" in b:
            pr.d["musik_uebergang"]["art"] = "blende" if b["art"] == "blende" else "direkt"
        if "dauer" in b:
            pr.d["musik_uebergang"]["dauer"] = float(np.clip(float(b["dauer"]), 0.3, 8.0))
        if "ziel" in b:
            z = b["ziel"]
            pr.d["ziel_dauer"] = float(z) if z not in (None, "", 0, "0") else None
        if "kuerzen" in b:
            pr.d["kuerzen"] = {k: v for k, v in b["kuerzen"].items() if v in ("vorne", "hinten")}
        pr.d["ende_weg"] = 0     # neue Längen-Einstellung: das Kürzen aus der Timeline gilt nicht mehr
        with pr.lock:
            pr.update_layout()
        pr.save()
        return musik_info(pr)
    if path == "/api/videos/boost":
        pr.boost = bool(b.get("an"))
        return {"boost": pr.boost}
    if path == "/api/videos/sortierung":
        pr.d["sortierung"] = "name" if b.get("art") == "name" else "zeit"
        pr.sort_clips()
        pr.save()
        if pr.erk is not None:
            pr.compute_erkennung()
        return videos_info(pr)
    if path == "/api/clip":
        name = b["name"]
        kw = {}
        for k in ("prio", "kat", "ton"):
            if k in b:
                kw[k] = b[k] or ""
        if "aus_weg" in b:   # abgewählte Stelle wieder erlauben
            u = pr.d["clips"].get(name, {})
            a0, a1 = b["aus_weg"]
            kw["aus"] = [x for x in u.get("aus", []) if not (abs(x[0] - a0) < 0.05 and abs(x[1] - a1) < 0.05)]
        pr.set_clip(name, **kw)
        if ("kat" in b or "prio" in b) and pr.erk is not None:
            pr.compute_erkennung()
        return {}
    if path == "/api/tage":
        return pr.tage_setzen(b.get("an"))
    if path == "/api/tage/teilen":
        return ER.nach_tagen_teilen(b.get("text", ""), pr.tage_info()["tage"])
    if path == "/api/ablauf":
        text = b.get("text", "")
        pr.d["beschreibung"] = text
        if isinstance(b.get("tage"), list):   # Ablauf je Tag
            tage = pr.tage_info()["tage"]
            texte = [str(x or "") for x in b["tage"]][:len(tage)]
            alle = str(b.get("alle") or "")
            pr.d["beschreibung_tage"] = {"tage": texte + [""] * (len(tage) - len(texte)), "alle": alle}
            neu = ER.parse_tage(texte, alle, tage, ER.sprache_des_textes(" ".join(texte + [alle]), get_lang()))
        else:
            neu = ER.parse_beschreibung(text, sprache=ER.sprache_des_textes(text, get_lang()))
        if b.get("ergaenzen"):
            have = {k["name"].lower() for k in pr.d["stichworte"]}
            pr.set_stichworte(pr.d["stichworte"] + [k for k in neu if k["name"].lower() not in have])
        else:
            pr.set_stichworte(neu)
        return {"stichworte": pr.d["stichworte"]}
    if path == "/api/stichworte":
        pr.set_stichworte(b.get("liste", []))
        return {"stichworte": pr.d["stichworte"]}
    if path == "/api/sprache":
        if KI.ki_python() is None:
            raise RuntimeError(_t("Für die Spracheingabe bitte zuerst die KI-Erkennung einrichten (Schritt 6) – "
                                 "oder den Ablauf eintippen."))
        ext = ".webm" if "webm" in ctype else (".ogg" if "ogg" in ctype else ".wav")
        f = pr.dirs["tmp"] / f"sprache{ext}"
        f.write_bytes(raw or b"")
        STATE.sprache_text = ""

        def job(j):
            j.text = _t("KI wird gestartet …")
            j.fortschritt = 0.02

            phase = {"p": "start"}

            def prog(a, bb, t):
                # Download zählt bis 40 %, Laden bis 50 %, die Erkennung selbst den Rest
                if t == _t("Sprachmodell wird heruntergeladen (einmalig) …"):
                    phase["p"] = "download"
                elif t == _t("Sprachmodell wird geladen …"):
                    phase["p"] = "laden"
                    j.fortschritt = max(j.fortschritt, 0.45)
                elif t == _t("Sprache wird erkannt …"):
                    phase["p"] = "erkennen"
                    j.fortschritt = max(j.fortschritt, 0.5)
                if t:
                    j.text = t
                if a is not None and bb:
                    anteil = min(1.0, a / bb)
                    j.fortschritt = 0.02 + 0.38 * anteil if phase["p"] == "download" else 0.5 + 0.49 * anteil
            STATE.sprache_text = KI.transkribieren(f, pr.dirs["tmp"], prog, sprache=get_lang())
            j.text = _t("Text erkannt")
        pr.start_job("sprache", job)
        return {}
    if path == "/api/erkennung/start":
        pr.start_job("erkennung", pr.erkennung_job, bool(b.get("mit_ki", True)))
        return {}
    if path == "/api/erkennung/antwort":
        pr.frage_antwort(b.get("id") or b.get("label"), b["antwort"], b.get("kw"))
        if b["antwort"] == "ja":
            pr.start_job("erkennung", pr.erkennung_job, True)
        else:
            pr.compute_erkennung()
        return {}
    if path == "/api/stichwort/neu":   # neues Stichwort für eine Szene oder einen Clip
        cl = pr.clip_by_name()
        if b.get("szene"):
            z = next((z for z in pr.scenes if z["id"] == b["szene"]), None)
            clips = list(z["clips"]) if z else []
        else:
            clips = [cl[b["clip"]]] if b.get("clip") in cl else []
        return {"stichwort": pr.neues_stichwort(b.get("name", ""), clips)}
    if path == "/api/szene/raus":   # ganze Szene nicht verwenden
        z = next((z for z in pr.scenes if z["id"] == b.get("id")), None)
        for c in (z["clips"] if z else []):
            pr.d["clips"].setdefault(c.name, {})["prio"] = "raus"
        pr.save()
        pr.apply_user_clip_settings()
        pr.compute_erkennung()
        return {}
    if path == "/api/szene/kw":   # ganze Szene in ein anderes Stichwort ("" = wieder automatisch)
        z = next((z for z in pr.scenes if z["id"] == b["id"]), None)
        if z:
            pr.clips_kw([c.name for c in z["clips"]], b.get("kw") or "")
        return {}
    if path == "/api/clips/kw":   # einzelne Clips in ein anderes Stichwort ("" = wieder automatisch)
        return {"n": pr.clips_kw([str(n) for n in b.get("namen") or []], b.get("kw") or "")}
    if path == "/api/szene":
        pr.set_scene(b.get("id"), menge=b.get("menge"), folge=b.get("folge") if isinstance(b.get("folge"), list) else None,
                     reset=bool(b.get("zuruecksetzen")))
        return dict({"erkennung": pr.erkennung_info()}, **gewichtung_info(pr))
    if path == "/api/block":
        pr.block_verschieben(b["kw"], b["nach"])
        return {"erkennung": pr.erkennung_info()}
    if path == "/api/gewichte":
        for k in pr.d["stichworte"]:
            if k["id"] in b:
                k["gewicht"] = float(np.clip(float(b[k["id"]]), 0, 5))
        pr.save()
        return gewichtung_info(pr)
    if path == "/api/schnitt" and b and set(b) <= {"originalton", "absenken"}:
        # Originalton-Schalter (auch in der Timeline): rückgängig machbar
        from .projekt import aktion

        def ton(p_):
            for k in ("originalton", "absenken"):
                if k in b:
                    p_.d["schnitt"][k] = b[k]
            p_.save()
        aktion("Originalton (ganzer Film) geändert")(ton)(pr)
        return api_get("/api/schnitt", {})
    if path == "/api/schnitt":
        s = pr.d["schnitt"]
        for k in ("k", "raster", "uebergang", "blende", "bewegung", "originalton", "absenken", "titel", "untertitel",
                  "abspann"):
            if k in b:
                s[k] = b[k]
        if isinstance(b.get("titelstil"), dict):
            from .titel import GROESSE as TI_GROESSE, STANDARD, STILE
            ts = dict(STANDARD, **(s.get("titelstil") or {}))
            for k in ("stil", "schrift", "farbe", "position"):
                if k in b["titelstil"]:
                    ts[k] = str(b["titelstil"][k])[:60]
            for k in ("groesse", "groesse_unter"):
                if k in b["titelstil"]:
                    ts[k] = int(np.clip(float(b["titelstil"][k] or 100), *TI_GROESSE))
            for k in ("fett", "fett_unter"):
                if k in b["titelstil"]:
                    ts[k] = bool(b["titelstil"][k])
            if ts["stil"] not in STILE:
                ts["stil"] = STANDARD["stil"]
            s["titelstil"] = ts
        s["k"] = int(s.get("k") or 0)
        s["blende"] = float(np.clip(float(s.get("blende") or 0.5), 0.1, 3.0))
        with pr.lock:
            pr.update_layout()
        pr.save()
        return api_get("/api/schnitt", {})
    if path == "/api/plan":
        return pr.plan(keep_locked=bool(b.get("behalten", True)))
    if path.startswith("/api/shot/"):
        op = path.rsplit("/", 1)[1]
        sid = b.get("id")
        if op == "slip":
            return pr.shot_slip(sid, float(b["src"]), bool(b.get("force")))
        if op == "laenge":
            return pr.shot_laenge(sid, int(b["k"]), bool(b.get("force")))
        if op == "verschieben":
            return pr.shot_move(sid, int(b["index"]))
        if op == "anders":
            return pr.shot_anders(sid)
        if op == "entfernen":
            return pr.shot_entfernen(sid, bool(b.get("stelle_sperren", True)), b.get("ausgleich", "rest"))
        if op == "sperren":
            return pr.shot_sperren(sid, bool(b.get("lock")))
        if op == "ton":
            return pr.shot_ton(sid, b.get("ton", ""))
        if op == "einfuegen":
            return pr.shot_einfuegen(sid, b.get("clip") or None,
                                     float(b["src"]) if b.get("src") not in (None, "") else None)
        raise KeyError(path)
    if path == "/api/auffuellen":
        return pr.auffuellen()
    if path == "/api/verlauf/zurueck":
        return pr.rueckgaengig(int(b.get("schritte", 1)))
    if path == "/api/verlauf/vor":
        return pr.wiederholen(int(b.get("schritte", 1)))
    if path == "/api/fertig":
        return pr.fertig_setzen(b.get("id"))
    if path == "/api/anteile/ok":
        return pr.anteile_ok()
    if path == "/api/anteile/ausgleichen":
        return pr.anteile_ausgleichen()
    if path == "/api/ende/zuruecknehmen":
        return pr.ende_zuruecknehmen()
    if path == "/api/export":
        fm = [f for f in b.get("formate", []) if f in EX.FORMATE]
        pr.start_job("export", pr.export_job, fm, bool(b.get("kdenlive", True)))
        return {}
    raise KeyError(path)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _file(self, path, ctype=None):
        path = Path(path)
        if not path.is_file():
            self.send_error(404)
            return
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                else:
                    start = max(0, size - int(b))
            except ValueError:
                pass
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "max-age=3600" if ctype.startswith("image/") else "no-cache")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = urllib.parse.unquote(u.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._file(resource("ui", "index.html"), "text/html; charset=utf-8")
            if p.startswith("/static/"):
                name = p[8:]
                if name == "qwebchannel.js":
                    return self._send(200, STATE.qwebchannel_js or b"/* kein Qt-Fenster */",
                                      "application/javascript")
                if not re.fullmatch(r"[a-z0-9_\-]+\.(js|css|svg|png)", name):
                    return self.send_error(404)
                return self._file(resource("ui", name))
            if p.startswith("/api/"):
                try:
                    return self._json(dict(api_get(p, q), ok=True))
                except KeyError:
                    return self._json({"ok": False, "fehler": _t("unbekannt")}, 404)
            pr = STATE.pr
            if pr is None:
                return self.send_error(404)
            if p.startswith("/bild/"):
                parts = p.split("/")
                if len(parts) == 4 and re.fullmatch(r"[0-9a-f]{12}", parts[2]) and re.fullmatch(r"f_\d+\.jpg", parts[3]):
                    return self._file(pr.dirs["bilder"] / parts[2] / parts[3], "image/jpeg")
                return self.send_error(404)
            m = re.fullmatch(r"/media/proxy/([0-9a-f]{12})\.webm", p)
            if m:
                return self._file(pr.dirs["proxy"] / f"{m.group(1)}.webm", "video/webm")
            m = re.fullmatch(r"/media/klick/(\d+)\.ogg", p)
            if m:
                f = pr.click_file(int(m.group(1)))
                return self._file(f, "audio/ogg")
            if p == "/media/mix.ogg":
                f = pr.music_mix_file()
                return self._file(f, "audio/ogg") if f else self.send_error(404)
            m = re.fullmatch(r"/media/titel/(\d)\.png", p)
            if m:
                f = pr.titel_vorschau(int(m.group(1)))
                return self._file(f, "image/png") if f else self.send_error(404)
            m = re.fullmatch(r"/media/titelstil/([a-z]+)\.png", p)
            if m:
                g = lambda k: q.get(k, [""])[0]   # noqa: E731
                return self._file(pr.stil_galerie(m.group(1), g("schrift"), g("farbe"), g("position") or "unten"),
                                  "image/png")
            return self.send_error(404)
        except Exception as e:
            traceback.print_exc()
            try:
                return self._json({"ok": False, "fehler": str(e)}, 200)
            except Exception:
                pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        p = urllib.parse.urlparse(self.path).path
        ctype = self.headers.get("Content-Type", "")
        try:
            body = {}
            if "json" in ctype and raw:
                body = json.loads(raw)
            res = api_post(p, body, raw, ctype)
            if not isinstance(res, dict):
                res = {}
            res.setdefault("ok", True)
            self._json(res)
        except KeyError as e:
            self._json({"ok": False, "fehler": f"{_t('unbekannt')}: {e}"}, 200)
        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "fehler": str(e)})


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """Abgebrochene Verbindungen (der Browser springt beim Abspielen im Video) sind normal – nicht melden."""
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def start_server(port=0):
    srv = Server(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    th = threading.Thread(target=srv.serve_forever, daemon=True, name="http")
    th.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"
