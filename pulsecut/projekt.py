"""Projekt: Zustand, Persistenz, Hintergrundaufgaben und alle Arbeitsschritte des Assistenten."""
import copy
import json
import re
import os
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

from . import erkennung as ER
from .i18n import L as _t, fmt_day_time, get_lang
from . import hwdec as HW
from . import ki as KI
from . import planer as PL
from .musik import AUDIO_EXT, MUSIC_VERSION, MusikLayout, analyse_music, render_clicktrack, render_music_mix
from .util import (CONFIG_HOME, FPS, atomic_write_json, low_priority, fmt_dur, log, md5, read_json, safe_name,
                   set_log_target)
from .video import (ANALYSE_VERSION, BEWEGUNG_LABEL, VIDEO_EXT, Clip, analyse_clip, compute_quality, keyframes_only,
                    make_proxy, motion_label, prepare_clip_arrays, segment_views, window_motion)

PROJEKT_DATEI = "pulsecut.json"
ALTE_PROJEKT_DATEI = "taktschnitt.json"   # Projekte aus Taktschnitt 1.0
FORMAT = 1
KW_FARBEN = ["#7b68c8", "#e76f51", "#f4a261", "#2a9d8f", "#5e60ce", "#e9c46a", "#d62828", "#3a86ff", "#8ac926",
             "#ff595e", "#6a4c93", "#1982c4", "#ff924c", "#52b788", "#b5179e", "#4d908e", "#c77dff", "#577590"]


def default_data(name, videos, musik):
    return {"format": FORMAT, "name": name, "videos": str(videos), "musik": str(musik),
            "erstellt": datetime.now().isoformat(timespec="seconds"),
            "musik_stuecke": [], "musik_korrektur": {}, "musik_uebergang": {"art": "direkt", "dauer": 2.0},
            "ziel_dauer": None, "kuerzen": {}, "sortierung": "zeit", "clips": {},
            "beschreibung": "", "stichworte": [], "abgelehnt": [], "szenen": {}, "szenen_folge": None,
            "schnitt": {"k": 0, "raster": "takt", "uebergang": "hart", "blende": 0.5, "bewegung": False,
                        "originalton": "auto", "absenken": 5, "titel": name, "untertitel": "", "abspann": "",
                        "titelstil": {"stil": "band", "schrift": "", "farbe": "#ffc23d", "position": "unten",
                                      "groesse": 100, "groesse_unter": 100, "fett": True, "fett_unter": False}},
            "timeline": None, "erledigt": []}


class Job:
    def __init__(self, name):
        self.name = name
        self.laeuft = False
        self.fortschritt = 0.0
        self.text = ""
        self.fehler = ""
        self.log = []
        self.fertig = 0.0

    def to_dict(self):
        return {"name": self.name, "laeuft": self.laeuft, "fortschritt": round(self.fortschritt, 3),
                "text": self.text, "fehler": self.fehler, "log": self.log[-8:], "fertig": self.fertig}


def _projekt_da(ordner):
    o = Path(ordner or "")
    return bool(ordner) and ((o / PROJEKT_DATEI).is_file() or (o / ALTE_PROJEKT_DATEI).is_file())


def recent_projects(alle=False):
    """Zuletzt geöffnete Projekte – nur die, deren Projektordner (mit Projektdatei) noch da ist. Gelöschte oder
    verschobene fallen aus der Liste; liegt ein Projekt auf einer gerade nicht eingesteckten Festplatte, taucht es
    wieder auf, sobald sie da ist (bis es von neueren verdrängt wird)."""
    lst = read_json(CONFIG_HOME / "zuletzt.json", []) or []
    return lst if alle else [x for x in lst if _projekt_da(x.get("ordner"))]


def remember_project(ordner, name):
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    lst = [x for x in recent_projects(alle=True) if x.get("ordner") != str(ordner)
           and (_projekt_da(x.get("ordner")) or not Path(x.get("ordner", "")).parent.exists())]
    lst.insert(0, {"ordner": str(ordner), "name": name, "zeit": datetime.now().isoformat(timespec="minutes")})
    atomic_write_json(CONFIG_HOME / "zuletzt.json", lst[:12])


class Projekt:
    def __init__(self, ordner):
        self.ordner = Path(ordner).expanduser().resolve()
        self.file = self.ordner / PROJEKT_DATEI
        old = self.ordner / ALTE_PROJEKT_DATEI
        if not self.file.exists() and old.exists():
            shutil.copy2(old, self.file)
        d = read_json(self.file)
        if not d:
            raise RuntimeError(_t("Kein Pulsecut-Projekt in {ordner}", ordner=self.ordner))
        base = default_data(d.get("name", "Projekt"), d.get("videos", ""), d.get("musik", ""))
        for k, v in base.items():
            if k not in d:
                d[k] = v
            elif isinstance(v, dict) and isinstance(d[k], dict):
                for kk, vv in v.items():
                    d[k].setdefault(kk, vv)
        self.d = d
        self.cache_dir = self.ordner / "cache"
        self.dirs = {k: self.cache_dir / k for k in ("bilder", "deskriptoren", "proxy", "emb", "tmp", "musik", "titel")}
        for p in self.dirs.values():
            p.mkdir(parents=True, exist_ok=True)
        self.export_dir = self.ordner / "export"
        self.cache_file = self.cache_dir / "analyse.json"
        self.cache = read_json(self.cache_file, {}) or {}
        if self.cache.get("format") != FORMAT:
            self.cache = {"format": FORMAT, "clips": {}, "meta": {}, "beats": {}, "ton": {}, "texte": {}}
        self.lock = threading.RLock()
        self.save_lock = threading.Lock()
        self.media_lock = threading.Lock()   # Klick-Spuren und Vorschau-Mix nicht doppelt erzeugen
        self.boost = False                    # Videoanalyse mit voller Rechenleistung
        self.jobs = {n: Job(n) for n in ("analyse", "musik", "ki", "erkennung", "sprache", "export", "plan")}
        self.clips = []
        self.tracks = []
        self.layout = None
        self.scenes = []
        self.erk = None
        self.voc_emb = None
        remember_project(self.ordner, d["name"])

    # ------------------------------------------------------------------ Anlegen / Speichern
    @staticmethod
    def erstellen(name, videos, musik, ordner=None):
        videos, musik = Path(videos).expanduser().resolve(), Path(musik).expanduser().resolve()
        if not videos.is_dir():
            raise RuntimeError(_t("Videoordner nicht gefunden: {p}", p=videos))
        if not musik.is_dir():
            raise RuntimeError(_t("Musikordner nicht gefunden: {p}", p=musik))
        name = name.strip() or videos.name
        ordner = Path(ordner).expanduser().resolve() if ordner else videos.parent / f"{safe_name(name)}_Pulsecut"
        ordner.mkdir(parents=True, exist_ok=True)
        f = ordner / PROJEKT_DATEI
        if f.exists():
            d = read_json(f) or {}
            d.update({"videos": str(videos), "musik": str(musik)})
        else:
            d = default_data(name, videos, musik)
        atomic_write_json(f, d)
        return Projekt(ordner)

    def save(self):
        with self.save_lock:
            atomic_write_json(self.file, self.d)

    def save_cache(self):
        with self.save_lock:
            tmp = Path(str(self.cache_file) + ".tmp")
            tmp.write_text(json.dumps(self.cache), encoding="utf-8")
            tmp.replace(self.cache_file)

    # ------------------------------------------------------------------ Hintergrundaufgaben
    def start_job(self, name, fn, *args):
        job = self.jobs[name]
        if job.laeuft:
            return False
        job.laeuft, job.fortschritt, job.text, job.fehler, job.log = True, 0.0, "", "", []

        def target():
            def hook(m):
                m = m.strip()
                if m:
                    job.log.append(m)
                    del job.log[:-40]
            set_log_target(hook)
            try:
                fn(job, *args)
                job.fertig = time.time()
            except Exception as e:   # Fehler sichtbar machen statt abstürzen
                job.fehler = str(e)
                traceback.print_exc()
            finally:
                job.laeuft = False
                job.fortschritt = 1.0
                set_log_target(None)

        threading.Thread(target=target, daemon=True, name=f"job-{name}").start()
        return True

    def job_status(self):
        return {n: j.to_dict() for n, j in self.jobs.items()}

    # ------------------------------------------------------------------ Videos
    def scan_videos(self):
        root = Path(self.d["videos"])
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT
                       and not p.name.startswith(".") and self.ordner not in p.parents)
        clips = []
        for i, f in enumerate(files):
            try:
                c = Clip(f, i)
            except OSError:
                continue
            meta = self.cache["meta"].get(c.key)
            try:
                if meta and "codec" in meta:
                    c.from_meta(meta)
                else:
                    c.probe()
                    self.cache["meta"][c.key] = c.to_meta()
            except Exception as e:
                log("  " + _t("{name}: nicht lesbar ({err})", name=f.name, err=str(e).splitlines()[0][:100]))
                continue
            if c.dur < 1.0:
                continue
            clips.append(c)
        self.apply_user_clip_settings(clips)
        return clips

    def apply_user_clip_settings(self, clips=None):
        for c in clips or self.clips:
            u = self.d["clips"].get(c.name, {})
            c.prio = u.get("prio", "")
            c.ton = u.get("ton", "") if u.get("ton") in ("an", "aus") else ""
            c.kat_manuell = u.get("kat", "")
            c.excl = [tuple(x) for x in u.get("aus", [])]

    def sort_clips(self):
        if self.d.get("sortierung") == "name":
            self.clips.sort(key=lambda c: (c.path.parent.as_posix().lower(), c.name.lower()))
        else:
            self.clips.sort(key=lambda c: (c.start, c.name.lower()))
        for i, c in enumerate(self.clips):
            c.order = i

    def analyse_job(self, job):
        job.text = _t("Videos werden eingelesen …")
        clips = self.scan_videos()
        if not clips:
            raise RuntimeError(_t("Keine Videos im Videoordner gefunden."))
        self.save_cache()
        todo = []
        for c in clips:
            ent = self.cache["clips"].get(c.key)
            ok = (ent and ent.get("v") == ANALYSE_VERSION and (self.dirs["deskriptoren"] / f"{c.hash}.npy").exists()
                  and all((self.dirs["bilder"] / c.hash / f[1]).exists() for f in ent.get("ki_frames", [])))
            if ok:
                c.ana = ent
            else:
                todo.append(c)
        need_proxy = [c for c in clips if not (self.dirs["proxy"] / f"{c.hash}.webm").exists()]
        total = sum(c.dur for c in todo) * 1.0 + sum(c.dur for c in need_proxy) * 0.35 + 1e-6
        done = [0.0]
        t0 = time.time()
        lk = threading.Lock()

        def with_hw(fn, c, *a):
            """Über den Grafikchip, wenn er für dieses Format taugt und frei ist – sonst/bei Fehler Prozessor."""
            err = None
            with HW.platz(c) as hw:
                if hw:
                    try:
                        return fn(c, *a, hw=True)
                    except Exception as e:
                        log("  " + _t("{name}: Grafikchip-Dekodierung gescheitert, nehme den Prozessor",
                                      name=c.name))
                        err = e
            res = fn(c, *a, hw=False)
            if err is not None:     # nur wenn es auf dem Prozessor klappt, liegt es am Chip
                HW.fehlgeschlagen(c, err)
            return res

        def work(c):
            low_priority()
            try:
                proxy_out = self.dirs["proxy"] / f"{c.hash}.webm"
                if c in todo:
                    # ein Durchgang: Analyse, Ton und (falls nötig) Vorschau-Video
                    together = c in need_proxy and not keyframes_only(c)
                    c.ana = with_hw(lambda cc, hw: analyse_clip(cc, self.dirs, proxy_out if together else None,
                                                                hw=hw), c)
                    with lk:
                        self.cache["clips"][c.key] = c.ana
                        done[0] += c.dur * (1.35 if together else 1.0)
                if c in need_proxy and not proxy_out.exists():
                    with_hw(lambda cc, hw: make_proxy(cc, proxy_out, hw=hw), c)
                    with lk:
                        done[0] += c.dur * 0.35
            except Exception as e:
                log("  " + _t("{name}: Analyse fehlgeschlagen ({err})", name=c.name, err=str(e).splitlines()[0][:120]))
                if c in todo:
                    c.ana = None
            with lk:
                job.fortschritt = min(0.99, done[0] / total)
                el = time.time() - t0
                eta = el / max(done[0], 1e-6) * (total - done[0])
                job.text = _t("Analysiere Videos … {name} – noch ca. {eta} min", name=c.name[:40], eta=fmt_dur(eta))

        job.text = _t("Analysiere {n} Videos ({m} aus dem Zwischenspeicher) …", n=len(todo), m=len(clips) - len(todo))
        work_items = list(dict.fromkeys(todo + need_proxy))
        # Leise: ein Arbeiter im Hintergrund. Volle Leistung (Schalter „Boost“): alle Kerne bis auf einen.
        # Die Zahl der gleichzeitig arbeitenden Threads richtet sich laufend nach dem Schalter.
        cond = threading.Condition()
        state = {"aktiv": 0, "fertig": 0}

        def limit():
            return max(2, (os.cpu_count() or 2) - 1) if self.boost else 1

        def loop():
            while True:
                with cond:
                    while state["aktiv"] >= limit() and work_items:
                        cond.wait(0.5)
                    if not work_items:
                        return
                    c = work_items.pop(0)
                    state["aktiv"] += 1
                try:
                    work(c)
                finally:
                    with cond:
                        state["aktiv"] -= 1
                        state["fertig"] += 1
                        if state["fertig"] % 8 == 0:
                            self.save_cache()
                        cond.notify_all()
        threads = [threading.Thread(target=loop, daemon=True, name=f"analyse-{i}")
                   for i in range(max(2, (os.cpu_count() or 2) - 1))]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.save_cache()
        clips = [c for c in clips if c.ana]
        for c in clips:
            c.desc = np.load(self.dirs["deskriptoren"] / f"{c.hash}.npy")
            c.dtimes = c.ana["dtimes"]
        compute_quality(clips)
        for c in clips:
            segment_views(c)
            prepare_clip_arrays(c)
        with self.lock:
            self.clips = clips
            self.sort_clips()
        job.text = _t("{n} Videos analysiert", n=len(clips))
        if "videos" not in self.d["erledigt"]:
            self.d["erledigt"].append("videos")
            self.save()

    def ready(self):
        return bool(self.clips) and not self.jobs["analyse"].laeuft

    def clip_by_name(self):
        return {c.name: c for c in self.clips}

    # ------------------------------------------------------------------ Musik
    def music_files(self):
        root = Path(self.d["musik"])
        files = sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT
                        and not p.name.startswith(".")), key=lambda p: p.name.lower()) if root.is_dir() else []
        known = {x["datei"]: x for x in self.d["musik_stuecke"]}
        order = [x["datei"] for x in self.d["musik_stuecke"] if any(f.name == x["datei"] for f in files)]
        order += [f.name for f in files if f.name not in order]
        self.d["musik_stuecke"] = [{"datei": n, "aktiv": known.get(n, {}).get("aktiv", True)} for n in order]
        return [(root / n, known.get(n, {}).get("aktiv", True)) for n in order]

    def analyse_track(self, path):
        st = Path(path).stat()
        fx = {k: v for k, v in (self.d["musik_korrektur"].get(Path(path).name) or {}).items() if v not in (None, 0, "")}
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}|{json.dumps(fx, sort_keys=True)}"
        b = self.cache["beats"].get(key)
        if not b or b.get("v") != MUSIC_VERSION:
            b = analyse_music(path, fx)
            self.cache["beats"][key] = b
        return dict(b, key=key, path=str(path), title=Path(path).stem, datei=Path(path).name, fix=fx)

    def musik_job(self, job):
        files = self.music_files()
        if not files:
            raise RuntimeError(_t("Keine Musik im Musikordner gefunden (wav, mp3, flac, m4a, ogg …)."))
        tracks = []
        for i, (p, aktiv) in enumerate(files):
            job.text = _t("Analysiere Musik: {name} …", name=p.name)
            job.fortschritt = i / len(files)
            try:
                t = self.analyse_track(p)
            except Exception as e:
                log(f"  {p.name}: {e}")
                continue
            t["aktiv"] = aktiv
            tracks.append(t)
        self.save_cache()
        with self.lock:
            self.tracks = tracks
            self.update_layout()
        self.save()
        job.fortschritt = 0.9
        self.prepare_audio(job)
        job.text = _t("{n} Musikstücke analysiert", n=len(tracks))

    def active_tracks(self):
        return [t for t in self.tracks if t.get("aktiv", True)]

    def update_layout(self):
        tr = self.active_tracks()
        if not tr:
            self.layout = None
            return None
        mu = self.d["musik_uebergang"]
        idx = {t["datei"]: i for i, t in enumerate(tr)}
        kz = {idx[n]: m for n, m in (self.d.get("kuerzen") or {}).items() if n in idx}
        self.layout = MusikLayout(tr, mu.get("art", "direkt"), mu.get("dauer", 2.0), self.d.get("ziel_dauer"), kz,
                                  self.d["schnitt"].get("raster", "takt"), self.d.get("ende_weg", 0))
        return self.layout

    def music_mix_file(self):
        layout = self.layout
        if not layout:
            return None
        f = self.dirs["musik"] / f"mix_{layout.signature()[:12]}.ogg"
        with self.media_lock:
            if not f.exists():
                for old in self.dirs["musik"].glob("mix_*.ogg"):
                    old.unlink(missing_ok=True)
                render_music_mix(layout, f)
        return f

    def click_path(self, t):
        return self.dirs["musik"] / f"klick_{md5(t['key'])[:12]}.ogg"

    def click_file(self, i):
        t = self.tracks[i]
        f = self.click_path(t)
        with self.media_lock:
            if not f.exists():
                render_clicktrack(t, f)
        return f

    def prepare_audio(self, job=None):
        """Klick-Spuren und Vorschau-Mix gleich vorbereiten, damit „Abspielen“ sofort klappt."""
        for i in range(len(self.tracks)):
            if job:
                job.text = _t("Bereite Klick-Spur vor: {name} …", name=self.tracks[i]["datei"])
            try:
                self.click_file(i)
            except Exception as e:
                log(f"  {self.tracks[i]['datei']}: {e}")
        try:
            self.music_mix_file()
        except Exception as e:
            log(f"  Mix: {e}")

    def set_music_fix(self, i, aktion, wert=None):
        t = self.tracks[i]
        name = t["datei"]
        fx = dict(self.d["musik_korrektur"].get(name) or {})
        if aktion == "frueher":
            fx["verschiebung"] = int(fx.get("verschiebung") or 0) - 1
        elif aktion == "spaeter":
            fx["verschiebung"] = int(fx.get("verschiebung") or 0) + 1
        elif aktion in ("halb", "doppelt", "tempo_auto"):
            fx["oktave"] = {"halb": -1, "doppelt": 1, "tempo_auto": 0}[aktion]
            fx.pop("bpm", None)
        elif aktion == "takt":
            fx["takt"] = int(wert) if str(wert) in ("3", "4") else 0
        elif aktion == "versatz":
            fx["versatz_ms"] = float(np.clip(float(fx.get("versatz_ms") or 0) + float(wert or 0), -150, 150))
        elif aktion == "bpm":
            try:
                v = float(str(wert).replace(",", "."))
            except ValueError:
                v = 0.0
            fx["bpm"] = v if 40 <= v <= 240 else 0
            fx.pop("oktave", None)
        elif aktion == "zuruecksetzen":
            fx = {}
        if fx.get("verschiebung"):
            fx["verschiebung"] = int(fx["verschiebung"]) % max(2, int(fx.get("takt") or t.get("takt") or 4))
        fx = {k: v for k, v in fx.items() if v not in (None, 0, "", False)}
        if fx:
            self.d["musik_korrektur"][name] = fx
        else:
            self.d["musik_korrektur"].pop(name, None)
        nt = self.analyse_track(t["path"])
        nt["aktiv"] = t.get("aktiv", True)
        with self.lock:
            self.tracks[i] = nt
            self.update_layout()
        self.save()
        self.save_cache()
        try:
            self.click_file(i)   # neue Klick-Spur gleich bereit haben
        except Exception as e:
            log(f"  {name}: {e}")
        return nt

    def set_music_order(self, order, aktiv):
        names = [t["datei"] for t in self.tracks]
        order = [n for n in order if n in names] + [n for n in names if n not in order]
        self.d["musik_stuecke"] = [{"datei": n, "aktiv": bool(aktiv.get(n, True))} for n in order]
        by = {t["datei"]: t for t in self.tracks}
        with self.lock:
            self.tracks = [by[n] for n in order]
            for t in self.tracks:
                t["aktiv"] = bool(aktiv.get(t["datei"], True))
            self.update_layout()
        self.save()

    def track_info(self, i):
        t = self.tracks[i]
        return {"i": i, "titel": t["title"], "datei": t["datei"], "aktiv": t.get("aktiv", True),
                "bpm": round(t["bpm"]), "takt": f"{t['takt']}/4", "meter": t["takt"],
                "taktlaenge": t["taktlaenge"], "takte": t["takte"], "dauer": round(t["ende"] - t["start"], 1),
                "fix": t.get("fix") or {}, "oktave_auto": t.get("oktave_auto", 0),
                "beats": [round(b, 3) for b in t["beats"]], "down": [1 if d else 0 for d in t["down"]],
                "kurve": t.get("kurve", [])[::2], "kurve_hz": t.get("kurve_hz", 10) / 2,
                "klick": f"/media/klick/{i}.ogg?k={md5(t['key'])[:10]}", "klick_bereit": self.click_path(t).exists(),
                "kuerzen": (self.d.get("kuerzen") or {}).get(t["datei"], "nein")}

    def layout_info(self):
        L = self.layout
        if not L:
            return None
        segs = [{"datei": L.tracks[s["track"]]["datei"], "titel": L.tracks[s["track"]]["title"],
                 "tl_start": round(s["tl_start"], 2), "src_in": round(s["src_in"], 2), "src_out": round(s["src_out"], 2),
                 "fade_in": s["fade_in"], "fade_out": s["fade_out"], "modus": s["modus"],
                 "gekuerzt": round(s["gekuerzt"], 1)} for s in L.segments]
        return {"dauer": round(L.D, 2), "info": L.info, "segmente": segs, "einheiten": len(L.units) - 1,
                "einheit": round(L.unit_len(), 3), "raster": L.raster, "kurve": L.curve(0.25),
                "units": [round(u, 3) for u in L.units], "wechsel": [round(x, 2) for x in L.switches],
                "mix": f"/media/mix.ogg?s={L.signature()[:10]}"}

    # ------------------------------------------------------------------ KI und Erkennung
    def clip_emb(self, c):
        f = self.dirs["emb"] / f"{c.hash}.npy"
        if f.exists():
            try:
                return np.load(f).astype(np.float32)
            except (OSError, ValueError):
                return None
        return None

    def kw_index(self):
        return {k["id"]: i for i, k in enumerate(self.d["stichworte"])}

    def erkennung_job(self, job, mit_ki=True):
        if not self.clips:
            raise RuntimeError(_t("Die Videos sind noch nicht analysiert."))
        kws = self.d["stichworte"]
        if not kws:
            raise RuntimeError(_t("Bitte zuerst den Ablauf beschreiben (Stichworte)."))
        have_ki = mit_ki and KI.ki_python() is not None
        if have_ki:
            def prog(a, b, text):
                if a is not None:
                    job.fortschritt = 0.05 + 0.75 * a / max(1, b)
                    job.text = _t("KI schaut sich die Videos an … {a}/{b}", a=a, b=b)
                elif text:
                    job.text = text
            job.text = _t("KI schaut sich die Videos an …")
            KI.bild_merkmale(self.clips, self.dirs["emb"], self.dirs["bilder"], self.dirs["tmp"], prog)
            if self.d["schnitt"].get("originalton", "auto") != "aus":
                job.text = _t("KI hört sich den Ton an (Lachen, Applaus, Musik) …")
                KI.ton_merkmale(self.clips, self.cache["ton"], self.dirs["tmp"], prog)
                self.save_cache()
            job.text = _t("Vergleiche mit deinen Stichworten …")
            texts = [ER.kw_text(k) for k in kws] + ER.voc_texts()
            T = KI.text_merkmale(texts, self.cache["texte"], self.dirs["tmp"])
            self.save_cache()
        else:
            T = None
        job.fortschritt = 0.9
        self.compute_erkennung(T)
        job.text = _t("Erkennung fertig")
        if "erkennung" not in self.d["erledigt"]:
            self.d["erledigt"].append("erkennung")
        self.save()

    def compute_erkennung(self, T=None):
        """Zuordnung Clip → Stichwort, Szenen, Unklares, Rückfragen."""
        kws = self.d["stichworte"]
        K = len(kws)
        # Videos, die unter „Videos“ auf Raus stehen, spielen für die Erkennung keine Rolle
        act = [c for c in self.clips if c.prio != "raus"]
        for c in self.clips:
            if c.prio == "raus":
                c.kw, c.kw_sicher, c._frame_sims = None, 1.0, None
        if T is None:
            T = self._text_matrix(kws, act)
        kw_emb = T[:K] if T is not None else np.zeros((0, 512))
        voc_emb = T[K:] if T is not None else None
        self.voc_emb = voc_emb
        sims, sims_voc = [], {}
        sim_kw = {}
        for c in act:
            E = self.clip_emb(c) if T is not None else None
            s = ER.clip_sims(E, kw_emb) if E is not None and len(kw_emb) else None
            sims.append(s)
            if s is not None:
                sim_kw[c.key] = s
                sims_voc[c.key] = ER.clip_sims(E, voc_emb)
                # Passung je Bild zum besten Stichwort → Bonus für Ausschnitte (wird nach der Zuordnung gesetzt)
                c._frame_sims = E @ kw_emb.T
            else:
                c._frame_sims = None
        idx = self.kw_index()
        manuell = {i: idx[c.kat_manuell] for i, c in enumerate(act) if c.kat_manuell in idx}
        if self.tage_aktiv():
            path, conf = self._zuordnen_nach_tagen(act, sims, kws, manuell)
        else:
            path, conf = ER.zuordnen(act, sims, kws, manuell)
        for c, k, p in zip(act, path, conf):
            c.kw = kws[k]["id"] if k is not None else None
            c.kw_sicher = p
        scenes = ER.szenen_bilden(act, path, conf, kws)
        frage = ER.rueckfragen(scenes, sim_kw, sims_voc, kw_emb, voc_emb if voc_emb is not None else np.zeros((0, 512)),
                               kws, set(self.d.get("abgelehnt") or []), idx, get_lang()) if T is not None else []
        self.erk = {"ki": T is not None and any(s is not None for s in sims), "fragen": frage}
        self.base_scenes = scenes
        self.kw_bonus = {}
        for c in act:
            fs = getattr(c, "_frame_sims", None)
            if fs is not None and c.kw in idx and len(fs):
                v = fs[:, idx[c.kw]]
                z = (v - v.mean()) / (v.std() + 1e-6)
                kt = [f[0] for f in c.ana["ki_frames"]]
                self.kw_bonus[c.key] = np.interp(c.grid, kt[:len(z)], z) if len(kt) >= 1 else None
        self.update_scenes()

    # ------------------------------------------------------------------ mehrere Tage
    def tage_aktiv(self):
        return bool(self.d.get("tage_modus")) and any(k.get("tag") for k in self.d["stichworte"])

    def tage_info(self):
        """Über welche Tage gehen die Videos, ist das sicher, und soll die Erkennung danach gehen?"""
        info = ER.tage_erkennen([c for c in self.clips if c.prio != "raus"])
        daten = [t["datum"] for t in info["tage"]]
        lang = get_lang()
        for i, t in enumerate(info["tage"]):
            t["nr"] = i + 1
            t["label"] = ER.tag_label(t["datum"], lang, kurz=False, alle_tage=daten)
            t["kurz"] = ER.tag_label(t["datum"], lang, alle_tage=daten)
        info["modus"] = self.d.get("tage_modus")
        info["texte"] = self.d.get("beschreibung_tage") or {"tage": [""] * len(daten), "alle": ""}
        return info

    def tage_setzen(self, an):
        self.d["tage_modus"] = bool(an)
        self.save()
        return self.tage_info()

    def _zuordnen_nach_tagen(self, act, sims, kws, manuell):
        """Je Tag getrennt zuordnen: Clips eines Tages bekommen nur Stichworte dieses Tages (und solche ohne Tag).
        Von Hand zugeordnete Clips behalten ihr Stichwort, auch wenn es zu einem anderen Tag gehört."""
        n = len(act)
        path, conf = [None] * n, [0.0] * n
        gruppen = {}
        for i, c in enumerate(act):
            gruppen.setdefault(ER.tag_von(c.start).isoformat(), []).append(i)
        for d, idxs in gruppen.items():
            kidx = {j for j, k in enumerate(kws) if k.get("tag") in (d, None, "")}
            kidx |= {manuell[i] for i in idxs if i in manuell}
            kidx = sorted(kidx) or list(range(len(kws)))
            sub_sims = [None if sims[i] is None else np.asarray(sims[i])[kidx] for i in idxs]
            sub_man = {p: kidx.index(manuell[i]) for p, i in enumerate(idxs) if i in manuell}
            sp, sc = ER.zuordnen([act[i] for i in idxs], sub_sims, [kws[j] for j in kidx], sub_man)
            for p, i in enumerate(idxs):
                path[i] = kidx[sp[p]] if sp[p] is not None else None
                conf[i] = sc[p]
        return path, conf

    def _tag_fuer(self, clips):
        """Tag (Datum) für ein neues Stichwort aus diesen Clips – nur wenn nach Tagen erkannt wird."""
        if not self.d.get("tage_modus") or not clips:
            return None
        first = min(clips, key=lambda c: c.order)
        return ER.tag_von(first.start).isoformat()

    def _kw_mit_tag(self, kw, tag):
        if tag:
            daten = [t["datum"] for t in ER.tage_erkennen([c for c in self.clips if c.prio != "raus"])["tage"]]
            kw["basis"] = kw["name"]
            kw["tag"] = tag
            kw["name"] = f"{kw['name']} · {ER.tag_label(tag, get_lang(), alle_tage=daten or None)}"[:40]
        return kw

    def _text_matrix(self, kws, act):
        """Text-Merkmale aus dem Zwischenspeicher. Fehlt ein Stichwort (neu angelegt oder umbenannt), steht für
        es der Mittelwert der Bilder, die du ihm von Hand zugeordnet hast – so geht es ohne erneuten KI-Lauf."""
        cache = self.cache["texte"]
        texts = [ER.kw_text(k) for k in kws]
        voc = ER.voc_texts()
        if not kws or not any(t in cache for t in texts) or not all(t in cache for t in voc):
            return None
        rows = []
        for k, t in zip(kws, texts):
            if t in cache:
                rows.append(np.asarray(cache[t], np.float32))
                continue
            proto = [self.clip_emb(c) for c in act if c.kat_manuell == k["id"]]
            proto = [p.astype(np.float32).mean(axis=0) for p in proto if p is not None and len(p)]
            v = np.mean(proto, axis=0) if proto else np.zeros(len(rows[0]) if rows else 512, np.float32)
            n = float(np.linalg.norm(v))
            rows.append(v / n if n > 0 else v)
        return np.vstack(rows + [np.asarray(cache[t], np.float32) for t in voc])

    def neues_stichwort(self, name, clips):
        """Neues Stichwort anlegen und diese Clips ihm zuordnen. Es kommt an die Stelle im Ablauf, an der die
        Clips zeitlich liegen."""
        name = (name or "").strip()[:40]
        if not name or not clips:
            raise RuntimeError(_t("Bitte einen Namen angeben."))
        kws = self.d["stichworte"]
        first = min(clips, key=lambda c: c.order)
        prev = [c for c in self.clips if c.order < first.order and c.prio != "raus" and c.kw and c not in clips]
        ids = [k["id"] for k in kws]
        pos = ids.index(prev[-1].kw) + 1 if prev and prev[-1].kw in ids else 0
        new = {"id": f"k{int(time.time() * 1000) % 10 ** 8}", "name": name, "text": name, "wiederkehrend": False,
               "gewicht": 1.0}
        self._kw_mit_tag(new, self._tag_fuer(clips))
        kws.insert(pos, new)
        for c in clips:
            self.d["clips"].setdefault(c.name, {})["kat"] = new["id"]
        self.save()
        self.apply_user_clip_settings()
        self.compute_erkennung()
        return new

    def update_scenes(self):
        """Szenen mit Menge und Filmreihenfolge (Standard: chronologisch / Reihenfolge der Videos)."""
        base = getattr(self, "base_scenes", None)
        if base is None:
            return []
        menge = self.d.get("szenen") or {}
        sc = []
        for z in base:
            z = dict(z)
            z["menge"] = menge.get(z["id"], "")
            sc.append(z)
        default = sorted(sc, key=lambda z: z["clips"][0].order)
        custom = self.d.get("szenen_folge")
        if custom:
            rank = {sid: i for i, sid in enumerate(custom)}
            res = sorted([z for z in default if z["id"] in rank], key=lambda z: rank[z["id"]])
            for di, z in enumerate(default):
                if z["id"] in rank:
                    continue
                ins = 0
                for prev in reversed(default[:di]):
                    if prev in res:
                        ins = res.index(prev) + 1
                        break
                res.insert(ins, z)
            sc = res
        else:
            sc = default
        self.scenes = sc
        return sc

    def erkennung_info(self):
        if self.erk is None:
            return None
        kws = self.d["stichworte"]
        colors = {k["id"]: KW_FARBEN[i % len(KW_FARBEN)] for i, k in enumerate(kws)}
        groups = []
        for k in kws:
            zs = [z for z in self.scenes if z["kw"] == k["id"]]
            groups.append({"kw": k["id"], "name": k["name"], "farbe": colors[k["id"]], "szenen": len(zs),
                           "clips": sum(len(z["clips"]) for z in zs),
                           "sekunden": round(sum(c.dur for z in zs for c in z["clips"]), 1)})
        scenes = [self.scene_info(z, colors) for z in self.scenes]
        unklar = [s["id"] for s in scenes if s["sicherheit"] < 0.55 and self.erk["ki"]]
        return {"ki": self.erk["ki"], "gruppen": groups, "szenen": scenes, "unklar": unklar,
                "ausgeschlossen": sum(1 for c in self.clips if c.prio == "raus"),
                "fragen": self.erk["fragen"], "farben": colors,
                "von_hand": bool(self.d.get("szenen_folge"))}

    def thumb(self, c, t):
        kf = c.ana.get("ki_frames", []) if c.ana else []
        if not kf:
            return None
        f = min(kf, key=lambda f: abs(f[0] - t))
        return f"/bild/{c.hash}/{f[1]}"

    def scene_info(self, z, colors=None, shots=None):
        cs = z["clips"]
        shots = shots if shots is not None else (self.d.get("timeline") or [])
        sh = [s for s in shots if s.get("szene") == z["id"]]
        pics = []
        for c in cs[:: max(1, len(cs) // 6)][:6]:
            pics.append(self.thumb(c, c.dur / 2))
        a, b = z["start"], z["end"]
        cl = []
        for c in cs:
            kf = c.ana.get("ki_frames", [])
            mine = sorted([s for s in sh if s["clip"] == c.name], key=lambda s: s["src"])
            cl.append({"name": c.name, "zeit": f"{c.start:%H:%M:%S}", "dauer": round(c.dur, 1), "prio": c.prio,
                       "hoch": c.portrait, "nutzbar": bool(c.segs), "kw_manuell": c.kat_manuell,
                       "sicher": round(getattr(c, "kw_sicher", 1.0), 2),
                       "bilder": [f"/bild/{c.hash}/{kf[int(round(i))][1]}"
                                  for i in np.linspace(0, len(kf) - 1, min(3, len(kf)))] if kf else [],
                       "schnitte": [{"id": s["id"], "src": round(s["src"], 2), "dur": round(s.get("dur", 0), 2),
                                     "tl": round(s.get("tl0", 0), 2), "bild": self.thumb(c, s["src"] + s.get("dur", 0) / 2)}
                                    for s in mine],
                       "aus": [{"a": round(x[0], 2), "b": round(x[1], 2), "bild": self.thumb(c, (x[0] + x[1]) / 2)}
                               for x in c.excl]})
        return {"id": z["id"], "kw": z["kw"], "farbe": (colors or {}).get(z["kw"], "#999"), "tag": a.strftime("%d.%m."),
                "zeit": fmt_day_time(a) + (f"–{b:%H:%M}" if (b - a).total_seconds() > 90 else ""),
                "n": len(cs), "bilder": [p for p in pics if p], "menge": z.get("menge", ""),
                "sicherheit": round(z.get("sicherheit", 1.0), 2), "clipliste": cl,
                "schnitte": len(sh), "sekunden": round(sum(s.get("dur", 0) for s in sh), 1),
                "tl0": round(min(s.get("tl0", 0) for s in sh), 2) if sh else None,
                "dauer": round(sum(c.dur for c in cs), 1)}

    # Stichworte & Antworten
    def set_stichworte(self, lst):
        clean = []
        used = set()
        daten = [t["datum"] for t in ER.tage_erkennen([c for c in self.clips if c.prio != "raus"])["tage"]] \
            if any(k.get("tag") for k in lst) else []
        for i, k in enumerate(lst):
            kid = str(k.get("id") or f"k{int(time.time() * 1000) % 100000}{i}")
            while kid in used:
                kid += "x"
            used.add(kid)
            e = {"id": kid, "name": str(k.get("name", "")).strip()[:40] or _t("Teil {n}", n=i + 1),
                 "text": str(k.get("text", "")).strip()[:400], "wiederkehrend": bool(k.get("wiederkehrend")),
                 "gewicht": float(k.get("gewicht", 1.0))}
            tag = str(k.get("tag") or "")
            if re.fullmatch(r"\d{4}-\d\d-\d\d", tag):
                # Name = Name ohne Tag + „ · Tag“ (auch wenn der Tag oder der Name geändert wurde)
                basis = e["name"].split(" · ")[0].strip() or e["name"]
                e.update(basis=basis, tag=tag)
                e["name"] = f"{basis} · {ER.tag_label(tag, get_lang(), alle_tage=daten or None)}"[:40]
            clean.append(e)
        self.d["stichworte"] = clean
        self.save()

    def frage_antwort(self, fid, antwort, kw=None):
        fr = next((f for f in (self.erk or {}).get("fragen", []) if fid in (f.get("id"), f["label"])), None)
        label = fr["id"] if fr else fid
        if antwort == "nein":
            self.d.setdefault("abgelehnt", []).append(label)
        elif antwort == "ja" and fr:
            # neues Stichwort an der passenden Stelle im Ablauf einfügen
            first = min((z for z in self.scenes if z["id"] in fr["szenen"]), key=lambda z: z["clips"][0].order, default=None)
            kws = self.d["stichworte"]
            pos = len(kws)
            if first is not None:
                prev_kw = None
                for z in sorted(self.scenes, key=lambda z: z["clips"][0].order):
                    if z is first:
                        break
                    prev_kw = z["kw"]
                ids = [k["id"] for k in kws]
                pos = ids.index(prev_kw) + 1 if prev_kw in ids else 0
            new = {"id": f"k{int(time.time()) % 100000}", "name": fr["label"], "text": fr["text"], "wiederkehrend": False,
                   "gewicht": 1.0}
            if first is not None:
                self._kw_mit_tag(new, self._tag_fuer(first["clips"]))
            kws.insert(pos, new)
            self.d.setdefault("abgelehnt", []).append(label)
        elif antwort == "zuordnen" and fr and kw:
            for z in self.scenes:
                if z["id"] in fr["szenen"]:
                    for c in z["clips"]:
                        self.d["clips"].setdefault(c.name, {})["kat"] = kw
            self.d.setdefault("abgelehnt", []).append(label)
        self.save()
        self.apply_user_clip_settings()

    def set_clip(self, name, **kw):
        u = self.d["clips"].setdefault(name, {})
        for k, v in kw.items():
            if v is None:
                continue
            if v in ("", [], None):
                u.pop(k, None)
            else:
                u[k] = v
        if not u:
            self.d["clips"].pop(name, None)
        self.save()
        self.apply_user_clip_settings()

    def set_scene(self, sid=None, menge=None, folge=None, reset=False):
        if menge is not None and sid:
            m = self.d.setdefault("szenen", {})
            if menge in PL.MENGE and menge:
                m[sid] = menge
            else:
                m.pop(sid, None)
        if folge is not None:
            self.d["szenen_folge"] = [str(x) for x in folge]
        if reset:
            self.d["szenen_folge"] = None
        self.save()
        self.update_scenes()

    def block_verschieben(self, kw, nach_kw):
        """Alle Szenen eines Stichworts hinter die letzte Szene eines anderen Stichworts setzen."""
        ids = [z["id"] for z in self.scenes]
        mine = [z["id"] for z in self.scenes if z["kw"] == kw]
        rest = [i for i in ids if i not in mine]
        if nach_kw == "__anfang__":
            pos = 0
        elif nach_kw == "__ende__":
            pos = len(rest)
        else:
            targets = [i for i, sid in enumerate(rest) if next(z for z in self.scenes if z["id"] == sid)["kw"] == nach_kw]
            pos = targets[-1] + 1 if targets else len(rest)
        self.set_scene(folge=rest[:pos] + mine + rest[pos:])

    # ------------------------------------------------------------------ Planung und Timeline
    def k_default(self):
        if not self.layout:
            return 2
        ul = self.layout.unit_len()
        return int(max(1, round(2.8 / ul))) if ul > 0 else 2

    def xf(self):
        s = self.d["schnitt"]
        return float(s.get("blende", 0.5)) if s.get("uebergang") == "blende" else 0.0

    def gewichte(self):
        return {k["id"]: float(k.get("gewicht", 1.0)) for k in self.d["stichworte"]}

    def make_planer(self):
        if not self.layout:
            raise RuntimeError(_t("Die Musik ist noch nicht bereit."))
        if not self.scenes:
            raise RuntimeError(_t("Es gibt noch keine Szenen – bitte zuerst die Erkennung ausführen."))
        s = self.d["schnitt"]
        k = int(s.get("k") or 0) or self.k_default()
        return PL.Planer(self.scenes, self.clip_by_name(), self.layout.units, k=k, xf=self.xf(),
                         gewichte=self.gewichte(), bewegung_vor_chrono=bool(s.get("bewegung")),
                         kw_bonus=getattr(self, "kw_bonus", {}))

    def plan(self, keep_locked=True, alle_sperren=False):
        with self.lock:
            self.update_layout()
            p = self.make_planer()
            old, _ = self.relayout()
            if keep_locked and self.fix_index(old) >= 0 and not alle_sperren:
                # fertiger Teil bleibt genau so; dahinter neu verteilen (gesperrte bleiben)
                tl = [s for s in old if self.fest(s)]
                self._fill(tl)
            else:
                if not keep_locked:
                    self.d["fertig_bis"] = None
                    self.d["ende_weg"] = 0
                    self.update_layout()
                    p = self.make_planer()
                locked = [s for s in old if s.get("lock") or alle_sperren] if keep_locked else []
                tl = p.plan(locked)
            for s in tl:
                s.setdefault("score", 0)
            self.settle(tl)
            self.d["anteile_basis"] = {k: round(v, 2) for k, v in self.anteile_ist(tl).items()}
            self.d["timeline"] = self.clean_timeline(tl)
            self.d["plan_warnungen"] = p.warn
            if "plan" not in self.d["erledigt"]:
                self.d["erledigt"].append("plan")
            self.save()
            return self.timeline_info()

    @staticmethod
    def clean_timeline(tl):
        keep = ("id", "clip", "src", "k", "lock", "szene", "manuell", "score", "bewegung", "bewegung_umsortiert", "t_edit",
                "ton")
        return [{k: s[k] for k in keep if k in s} for s in tl]

    def relayout(self):
        tl = self.d.get("timeline") or []
        if self.layout is None:
            return tl, 0
        diff = PL.layout(tl, self.layout.units)
        cl = self.clip_by_name()
        for s in tl:
            c = cl.get(s["clip"])
            if c is not None and s["dur"] > 0:
                s["bewegung"] = motion_label(window_motion(c, s["src"], s["dur"]))
        self._markiere_fix(tl)
        return tl, diff

    # ------------------------------------------------------------------ „fertig bis hier“
    # Alles bis zu diesem Schnitt gilt als fertig: Auffüllen, Ausgleichen und Neuplanen ändern dort nichts mehr.
    # Die Markierung wandert mit jeder Bearbeitung nach hinten mit (nie zurück) und lässt sich von Hand setzen.
    def fix_index(self, tl):
        fid = self.d.get("fertig_bis")
        if not fid:
            return -1
        return next((i for i, s in enumerate(tl) if s["id"] == fid), -1)

    def _markiere_fix(self, tl):
        fi = self.fix_index(tl)
        for i, s in enumerate(tl):
            if i <= fi:
                s["_fix"] = True
            else:
                s.pop("_fix", None)
        return fi

    def _fix_bis(self, tl, idx):
        """Markierung bis Position idx vorrücken (nur nach hinten)."""
        if 0 <= idx < len(tl) and idx > self.fix_index(tl):
            self.d["fertig_bis"] = tl[idx]["id"]
        return self._markiere_fix(tl)

    @staticmethod
    def fest(s):
        """Darf die Automatik diesen Schnitt ändern? Nicht, wenn gesperrt oder im fertigen Teil."""
        return bool(s.get("lock") or s.get("_fix"))

    def fertig_setzen(self, sid):
        """Markierung von Hand setzen (auch zurück); sid=None hebt sie auf."""
        with self.lock:
            tl, _ = self.relayout()
            self.d["fertig_bis"] = sid if sid and any(s["id"] == sid for s in tl) else None
            self.save()
            return {"ok": True, "fertig_bis": self.d["fertig_bis"]}

    # ------------------------------------------------------------------ Anteile der Kategorien
    def anteile_soll(self):
        """Sekunden je Stichwort nach der Gewichtung (wie in Schritt 7 angezeigt)."""
        try:
            p = self.make_planer()
        except RuntimeError:
            return {}
        alloc = p.allocate(p.N, {})
        L = p.L_of(p.k)
        out = {}
        for z in self.scenes:
            out[z["kw"]] = out.get(z["kw"], 0.0) + alloc.get(z["id"], 0) * L
        return out

    def anteile_ist(self, tl):
        zkw = {z["id"]: z["kw"] for z in self.scenes}
        out = {}
        for s in tl:
            kw = zkw.get(s.get("szene"))
            if kw:
                out[kw] = out.get(kw, 0.0) + float(s.get("dur") or 0.0)
        return out

    def anteile_ziel(self):
        """Bezug für Abweichungen und Ausgleich: der Stand nach dem letzten Planen (oder „so lassen“), sonst die
        Gewichtung."""
        b = self.d.get("anteile_basis")
        if b:
            return {k: float(v) for k, v in b.items()}
        soll = self.anteile_soll()
        tot = sum(soll.values()) or 1.0
        D = self.layout.D if self.layout else 0.0
        return {k: v / tot * D for k, v in soll.items()}

    def abweichungen(self, tl):
        if not self.layout or not tl:
            return []
        ref, ist = self.anteile_ziel(), self.anteile_ist(tl)
        D = self.layout.D or 1.0
        k = int(self.d["schnitt"].get("k") or 0) or self.k_default()
        L = self.layout.unit_len() * k
        name = {x["id"]: x["name"] for x in self.d["stichworte"]}
        out = []
        for kw in set(ref) | set(ist):
            d = ist.get(kw, 0.0) - ref.get(kw, 0.0)
            if abs(d) > max(0.03 * D, 1.5 * L) and kw in name:   # mehr als 1½ Schnitte bzw. 3 Prozentpunkte
                out.append({"kw": kw, "name": name[kw], "ist": round(100 * ist.get(kw, 0.0) / D),
                            "soll": round(100 * ref.get(kw, 0.0) / D), "diff": round(d, 1)})
        return sorted(out, key=lambda x: -abs(x["diff"]))

    def anteile_ok(self):
        with self.lock:
            tl, _ = self.relayout()
            self.d["anteile_basis"] = {k: round(v, 2) for k, v in self.anteile_ist(tl).items()}
            self.save()
            return {"ok": True}

    def anteile_ausgleichen(self):
        """Hinter „fertig bis hier“ Schnitte zu stark vertretener Kategorien gegen Schnitte zu schwach vertretener tauschen."""
        with self.lock:
            tl, _ = self.relayout()
            ref = self.anteile_ziel()

            def fehler(t):
                PL.layout(t, self.layout.units)
                ist = self.anteile_ist(t)
                return sum(abs(ist.get(kw, 0.0) - ref.get(kw, 0.0)) for kw in set(ref) | set(ist))
            zkw = {z["id"]: z["kw"] for z in self.scenes}
            start_err = fehler(tl)
            for _ in range(24):
                before = fehler(tl)
                ist = self.anteile_ist(tl)
                over = sorted(ref.keys() | ist.keys(), key=lambda kw: -(ist.get(kw, 0.0) - ref.get(kw, 0.0)))
                trial = None
                for kw in over:
                    if ist.get(kw, 0.0) - ref.get(kw, 0.0) <= 0:
                        break
                    cand = [x for x in tl if zkw.get(x.get("szene")) == kw and not self.fest(x)]
                    if cand:
                        trial = copy.deepcopy(tl)
                        weg = min((x for x in trial if x["id"] in {c["id"] for c in cand}),
                                  key=lambda x: x.get("score", 0))
                        trial.remove(weg)
                        self._zuteilen(trial, int(weg["k"]), ziel=ref)
                        break
                if trial is None or fehler(trial) >= before - 0.5:
                    break
                tl = trial
            verbessert = fehler(tl) < start_err - 0.5
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True, "verbessert": verbessert}

    # ------------------------------------------------------------------ freie Takte verteilen
    def _platz(self, tl, s, add):
        """Passt der Schnitt mit `add` Einheiten mehr (an seiner Stelle) samt seinen Geschwistern in den Clip?"""
        cl = self.clip_by_name()
        c, units, xf = cl[s["clip"]], self.layout.units, self.xf()
        N = len(units) - 1
        u0 = s.get("u0", 0)
        dur = units[min(N, u0 + int(s["k"]) + add)] - units[min(N, u0)]
        others = sum(x.get("dur", 0) + xf + PL.GAP for x in tl if x["clip"] == s["clip"] and x is not s)
        return dur + xf + 2 * PL.EDGE + others <= c.dur

    def _laenger(self, tl, rest, cands, gleichmaessig=True):
        """Schnitte aus cands um insgesamt rest Einheiten verlängern (nacheinander oder reihum)."""
        guard = 0
        while rest > 0 and guard < 400:
            guard += 1
            progress = False
            for s in cands:
                if rest <= 0:
                    break
                while rest > 0 and s in tl and self._platz(tl, s, 1):
                    s["k"] = int(s["k"]) + 1
                    rest -= 1
                    progress = True
                    PL.layout(tl, self.layout.units)
                    if gleichmaessig:
                        break
            if not progress:
                break
        return rest

    def _chrono_clips(self, tl, zid, clips, pos, ausser=None):
        """Clips der Szene, aus denen an Position pos etwas kommen darf, ohne die Zeitfolge gegenüber dem fertigen Teil
        zu brechen: zeitlich nach dem letzten fertigen Schnitt dieser Szene davor und vor dem ersten fertigen danach."""
        if self.d["schnitt"].get("bewegung"):
            return list(clips)
        cl = self.clip_by_name()
        lo = hi = None
        for i, x in enumerate(tl):
            if x is ausser or x.get("szene") != zid or not x.get("_fix") or x.get("manuell"):
                continue
            c = cl.get(x["clip"])
            if c is None:
                continue
            key = (c.start, c.idx)
            if i < pos and (lo is None or key > lo):
                lo = key
            if i > pos and (hi is None or key < hi):
                hi = key
        if lo is None and hi is None:
            return list(clips)
        return [c for c in clips if (lo is None or (c.start, c.idx) > lo) and (hi is None or (c.start, c.idx) < hi)]

    def _platz_schaffen(self, tl, delta, schuetzen, key):
        """Zu viele Einheiten (länger als die Musik): erst ungesperrte Schnitte hinter „fertig bis hier“ weg (Reihenfolge
        key), dann dort Schnitte kürzer, notfalls auch im fertigen Teil – die Musiklänge ist eine harte Regel."""
        for stufe in (lambda x: not self.fest(x), lambda x: not x.get("lock")):
            for x in sorted([x for x in tl if all(x is not y for y in schuetzen) and stufe(x)], key=key):
                if delta <= 0:
                    return 0
                if int(x["k"]) <= delta or int(x["k"]) == 1:
                    tl.remove(x)
                    delta -= int(x["k"])
            for x in [x for x in tl if all(x is not y for y in schuetzen) and stufe(x)]:
                while delta > 0 and int(x["k"]) > 1:
                    x["k"] = int(x["k"]) - 1
                    delta -= 1
            if delta <= 0:
                return 0
        return max(0, delta)

    def _start_hinter_fix(self, tl):
        fixed = [i for i, s in enumerate(tl) if s.get("_fix")]
        return (max(fixed) + 1) if fixed else 0

    def _zuteilen(self, tl, rest, ab=None, ziel=None, log=None):
        """rest Einheiten hinter „fertig bis hier“ (bzw. ab Position ab) verteilen: neue Schnitte aus freiem Material in
        der Kategorie, die am weitesten unter ihrem Anteil liegt – chronologisch in ihre Szene eingereiht, nie in eine
        Szene vor dieser Stelle. Reicht das Material nicht, werden die Schnitte dahinter reihum länger.
        Gibt zurück, was sich nicht unterbringen ließ."""
        if rest <= 0 or not self.layout:
            return max(0, rest)
        units = self.layout.units
        start = self._start_hinter_fix(tl) if ab is None else max(ab, self._start_hinter_fix(tl))
        k = int(self.d["schnitt"].get("k") or 0) or self.k_default()
        zorder = [z["id"] for z in self.scenes]
        if start < len(tl):
            z0 = tl[start].get("szene")
        elif tl:
            z0 = tl[-1].get("szene")
        else:
            z0 = zorder[0] if zorder else None
        i0 = zorder.index(z0) if z0 in zorder else 0
        erlaubt = [z for z in self.scenes[i0:] if PL.MENGE.get(z.get("menge", ""), 1.0) > 0]
        ref = ziel if ziel is not None else self.anteile_ziel()
        name = {x["id"]: x["name"] for x in self.d["stichworte"]}
        xf = self.xf()
        guard = 0
        while rest >= k and guard < 80:
            guard += 1
            PL.layout(tl, units)
            ist = self.anteile_ist(tl)
            L = self.layout.unit_len() * k
            best = None
            for z in erlaubt:
                proto = {"id": "neu", "clip": "", "src": 0.0, "dur": L, "k": k}
                cand = PL.best_free_window(tl, proto, self._chrono_clips(tl, z["id"], z["clips"], start), xf,
                                           slack=self._slack(proto))
                if not cand:
                    continue
                have = sum(1 for x in tl if x.get("szene") == z["id"])
                key = ref.get(z["kw"], 0.0) - ist.get(z["kw"], 0.0) - 0.25 * L * have + 0.01 * cand[0]
                if best is None or key > best[0]:
                    best = (key, z, cand)
            if not best:
                break
            _, z, cand = best
            new = {"id": PL.new_id(), "clip": cand[1], "src": round(cand[2], 3), "k": k, "lock": False, "szene": z["id"]}
            idxs = [i for i, x in enumerate(tl) if i >= start and x.get("szene") == z["id"]]
            if idxs:
                pos = idxs[-1] + 1
            else:
                later = set(zorder[zorder.index(z["id"]) + 1:])
                pos = next((i for i, x in enumerate(tl) if i >= start and x.get("szene") in later), len(tl))
            tl.insert(max(pos, start), new)
            rest -= k
            self._resort_scene(tl, z["id"])
            if log is not None:
                log.append({"art": "neu", "kw": name.get(z["kw"], "")})
        if rest > 0:
            PL.layout(tl, units)
            cands = [x for i, x in enumerate(tl) if i >= start and not self.fest(x)]
            vor = rest
            rest = self._laenger(tl, rest, cands, gleichmaessig=True)
            if log is not None and vor > rest:
                log.append({"art": "laenger", "n": vor - rest})
        return rest

    def timeline_info(self):
        tl, diff = self.relayout()
        cl = self.clip_by_name()
        kws = self.d["stichworte"]
        colors = {k["id"]: KW_FARBEN[i % len(KW_FARBEN)] for i, k in enumerate(kws)}
        kwname = {k["id"]: k["name"] for k in kws}
        zkw = {z["id"]: z["kw"] for z in self.scenes}
        allow = bool(self.d["schnitt"].get("bewegung"))
        probs = PL.check(tl, cl, self.xf(), allow_unchrono=allow) if tl else []
        bad = {i for p in probs if p["art"] in ("ueberlappung", "rand") for i in p["ids"]}
        shots = []
        for s in tl:
            c = cl.get(s["clip"])
            if c is None:
                continue
            kw = zkw.get(s.get("szene"))
            shots.append({"id": s["id"], "clip": c.name, "hash": c.hash, "src": round(s["src"], 3), "k": s["k"],
                          "tl0": round(s["tl0"], 3), "tl1": round(s["tl1"], 3), "dur": round(s["dur"], 3),
                          "lock": bool(s.get("lock")), "szene": s.get("szene"), "kw": kw,
                          "name": kwname.get(kw, ""), "farbe": colors.get(kw, "#888"),
                          "bewegung": s.get("bewegung", "ruhig"), "bewegung_text": _t(BEWEGUNG_LABEL.get(s.get("bewegung", "ruhig"), "ruhig")),
                          "ueber": bool(s.get("ueber")), "problem": s["id"] in bad,
                          "proxy": f"/media/proxy/{c.hash}.webm", "clipdauer": round(c.dur, 2),
                          "hoch": c.portrait, "aspect": round(c.aspect, 4), "bild": self.thumb(c, s["src"] + s["dur"] / 2),
                          "atmo": s.get("atmo"), "ton": s.get("ton", ""), "fertig": bool(s.get("_fix"))})
        lay = self.layout_info()
        return {"shots": shots, "probleme": probs, "differenz": diff, "absenken": self.absenkung_db(),
                "originalton": self.d["schnitt"].get("originalton", "auto"),
                "fertig_bis": self.d.get("fertig_bis") if self.fix_index(tl) >= 0 else None,
                "abweichungen": self.abweichungen(tl), "ende_weg": int(self.d.get("ende_weg") or 0),
                "ende_auto": bool(self.d.get("ende_auto")), "k": int(self.d["schnitt"].get("k") or 0) or self.k_default(),
                "xf": self.xf(), "musik": lay, "warnungen": self.d.get("plan_warnungen", []),
                "titel": self.titles_info(), "dauer": lay["dauer"] if lay else 0}

    def titles_info(self):
        s = self.d["schnitt"]
        D = self.layout.D if self.layout else 0
        out = []
        if s.get("titel"):
            out.append({"text": s["titel"], "unter": s.get("untertitel", ""), "t0": 0.8, "t1": min(6.5, D * 0.3),
                        "art": "titel"})
        if s.get("abspann"):
            out.append({"text": s["abspann"], "unter": "", "t0": max(D - 8.0, D * 0.8), "t1": D, "art": "abspann"})
        sig = md5(json.dumps([[t["text"], t["unter"]] for t in out] + [self.titelstil()], sort_keys=True))[:10]
        for j, t in enumerate(out):   # Vorschau-Bild in genau der Gestaltung des Exports
            t["bild"] = f"/media/titel/{j}.png?k={sig}"
        return out

    def titelstil(self):
        from .titel import STANDARD, STILE
        st = dict(STANDARD, **(self.d["schnitt"].get("titelstil") or {}))
        if st["stil"] not in STILE:
            st["stil"] = STANDARD["stil"]
        return st

    def titel_vorschau(self, j, W=960, H=540):
        """Titelbild j (0 = Titel, 1 = Abspann) für die Live-Vorschau."""
        from .export import title_pngs
        ts = self.titles_info()
        if j >= len(ts):
            return None
        return title_pngs([ts[j]], self.dirs["titel"], self.dirs["tmp"], W, H, self.titelstil())[0][0]

    def stil_galerie(self, sid, schrift="", farbe="", position="unten", W=480, H=270):
        """Kleines Vorschaubild einer Titel-Gestaltung über einem Bild aus dem Film."""
        from . import titel as TI
        from .util import run as _run, write_png
        s = self.d["schnitt"]
        akt = self.titelstil()
        stil = {"stil": sid, "schrift": schrift, "farbe": farbe or TI.STANDARD["farbe"], "position": position,
                "groesse": akt.get("groesse", 100), "groesse_unter": akt.get("groesse_unter", 100),
                "fett": akt.get("fett", True), "fett_unter": akt.get("fett_unter", False)}
        key = md5(json.dumps([stil, s.get("titel"), s.get("untertitel"), W, H], sort_keys=True))[:12]
        out = self.dirs["titel"] / f"galerie_{key}.png"
        if out.exists():
            return out
        bg = None
        frames = [self.dirs["bilder"] / c.hash / c.ana["ki_frames"][len(c.ana["ki_frames"]) // 2][1]
                  for c in self.clips if c.ana and c.ana.get("ki_frames") and not c.portrait and c.prio != "raus"]
        if frames:
            f = frames[len(frames) // 3]
            raw = _run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(f), "-vf", f"scale={W}:{H}", "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], binary=True, check=False)
            if raw and len(raw) == W * H * 3:
                bg = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
        if bg is None:
            bg = np.zeros((H, W, 3), np.uint8)
            bg[:] = (70, 90, 110)
        rgba = TI.render(s.get("titel") or self.d["name"], s.get("untertitel", ""), W, H, stil, "titel", self.dirs["tmp"])
        write_png(out, TI.vorschau_auf(bg, rgba))
        return out

    def find_shot(self, sid):
        tl = self.d.get("timeline") or []
        return next((s for s in tl if s["id"] == sid), None), tl

    def scene_clips(self, sid):
        z = next((z for z in self.scenes if z["id"] == sid), None)
        return z["clips"] if z else []

    # Bearbeitung
    def shot_slip(self, sid, src, force=False):
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            c = self.clip_by_name()[sh["clip"]]
            xf = self.xf()
            rg = PL.slip_range(tl, sh, c, xf)
            src = float(np.clip(src, rg["min"], rg["max"]))
            block = PL.blocked_by(tl, sh, src, xf)
            if block and not force:
                return {"ok": False, "kollision": [{"id": b["id"], "tl": round(b["tl0"], 2), "lock": bool(b.get("lock"))}
                                                   for b in block], "bereich": rg}
            sh["src"] = round(src, 3)
            sh["lock"] = True
            sh["t_edit"] = time.time()
            for b in block:   # aufgegebene Nachbarn: neue Stelle in ihrer Szene suchen (oder entfernen)
                self._reassign(tl, b, exclude={sh["id"]})
            sh.pop("_fix", None)     # der bearbeitete Schnitt darf in seiner Szene neu einsortiert werden
            self._resort_scene(tl, sh.get("szene"), auch_fertig=True)
            self._markiere_fix(tl)
            self._fix_bis(tl, tl.index(sh))
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def settle(self, tl):
        """Nach jeder Änderung: aufs Raster legen und die harten Regeln herstellen.
        Reihenfolge der Mittel: minimal verschieben → Schnitt passt allein nicht in seinen Clip: 1 Takt kürzer →
        ungesperrten Schnitt des betroffenen Clips an eine freie Stelle seiner Szene setzen (oder ersetzen) →
        sind nur gesperrte beteiligt, hat die zuletzt gemachte Änderung Vorrang (der ältere wird freigegeben)."""
        if not self.layout:
            return tl
        cl = self.clip_by_name()
        xf = self.xf()
        for _ in range(12):
            PL.layout(tl, self.layout.units)
            PL.repair(tl, cl, xf)
            probs = [p for p in PL.check(tl, cl, xf, allow_unchrono=True) if p["art"] in ("ueberlappung", "rand")]
            if not probs:
                break
            names = list(dict.fromkeys(next(s["clip"] for s in tl if s["id"] == p["ids"][0]) for p in probs))
            fixed = False
            for n in names:   # 1) passt allein nicht
                for v in [s for s in tl if s["clip"] == n]:
                    if int(v["k"]) > 1 and v["dur"] + xf + 2 * PL.EDGE > cl[n].dur:
                        v["k"] = int(v["k"]) - 1
                        PL.layout(tl, self.layout.units)
                        self._fill(tl, settle=False)
                        fixed = True
                        break
                if fixed:
                    break
            if fixed:
                continue
            for n in names:   # 2) einen ungesperrten Schnitt dieses Clips woanders hin
                cand = sorted([s for s in tl if s["clip"] == n and not self.fest(s)], key=lambda s: -tl.index(s)) \
                    or sorted([s for s in tl if s["clip"] == n and not s.get("lock")], key=lambda s: -tl.index(s))
                # (die harten Regeln gehen vor: notfalls darf auch ein Schnitt im fertigen Teil eine andere Stelle bekommen)
                for v in cand:
                    sc = self._chrono_clips(tl, v.get("szene"), self.scene_clips(v.get("szene")), tl.index(v), ausser=v)
                    best = PL.best_free_window(tl, v, [c for c in sc if c.name != n] or [cl[n]], xf,
                                               slack=self._slack(v))
                    if best:
                        v["clip"], v["src"] = best[1], round(best[2], 3)
                        self._resort_scene(tl, v.get("szene"))
                    else:
                        tl.remove(v)
                        PL.layout(tl, self.layout.units)
                        self._fill(tl, settle=False)
                    fixed = True
                    break
                if fixed:
                    break
            if fixed:
                continue
            for n in names:   # 3) nur gesperrte: der älteste wird freigegeben
                locked = [s for s in tl if s["clip"] == n and self.fest(s)]
                frei = [s for s in locked if not s.get("_fix")] or [s for s in locked if s.get("lock")]
                # (lieber einen gesperrten hinter „fertig bis hier“ freigeben; die harten Regeln gehen aber vor)
                if len(locked) >= 2 and frei:
                    v = min(frei, key=lambda s: s.get("t_edit", 0))
                    v["lock"] = False
                    v.pop("manuell", None)
                    fixed = True
                    break
            if not fixed:
                break
        PL.layout(tl, self.layout.units)
        return tl

    def _slack(self, sh):
        """Reserve für neue Stellen: Ein Schnitt kann beim Verschieben im Raster in einen langsameren Teil der Musik
        rutschen und länger werden. Mit der längsten möglichen Dauer gewählte Stellen passen überall."""
        u = self.layout.units if self.layout else []
        k = max(1, int(sh.get("k") or 1))
        spans = [u[i + k] - u[i] for i in range(len(u) - k)]
        return max(0.15, (max(spans) if spans else 0.0) - float(sh.get("dur") or 0.0) + 0.05)

    def _reassign(self, tl, b, exclude=()):
        b.pop("_fix", None)      # aufgegeben: darf (auch im fertigen Teil) neu einsortiert werden
        clips = self._chrono_clips(tl, b.get("szene"), self.scene_clips(b.get("szene")), tl.index(b), ausser=b)
        best = PL.best_free_window(tl, b, clips, self.xf(), exclude_ids=(), slack=self._slack(b))
        if best:
            b["clip"], b["src"] = best[1], round(best[2], 3)
            b["lock"] = False
        else:
            tl.remove(b)
            self._fill(tl)

    def _resort_scene(self, tl, zid, auch_fertig=False):
        """Schnitte einer Szene (auf ihren Plätzen) chronologisch ordnen – außer von Hand umsortierte und (wenn nicht
        ausdrücklich gewollt, z. B. nach einer Bearbeitung dort) die im fertigen Teil."""
        if zid is None or self.d["schnitt"].get("bewegung"):
            return
        cl = self.clip_by_name()
        pos = [i for i, s in enumerate(tl) if s.get("szene") == zid and not s.get("manuell")
               and (auch_fertig or not s.get("_fix"))]
        items = sorted([tl[i] for i in pos], key=lambda s: (cl[s["clip"]].start, cl[s["clip"]].idx, s["src"]))
        for i, s in zip(pos, items):
            tl[i] = s

    def _fill(self, tl, settle=True):
        """Fehlende Raster-Einheiten bis zum Musikende ergänzen – nur hinter „fertig bis hier“, nach den Anteilen."""
        if not self.layout:
            return
        N = len(self.layout.units) - 1
        PL.layout(tl, self.layout.units)
        rest = N - sum(int(s["k"]) for s in tl)
        if rest > 0:
            rest = self._zuteilen(tl, rest)
        if rest > 0 and tl:
            rest = PL.distribute_rest(tl, self.clip_by_name(), self.layout.units, self.xf())
        if rest > 0 and tl:
            # nirgends mehr Material: lieber endet die Musik entsprechend früher (mit Ausblendung) als ein Loch im Bild
            self.d["ende_weg"] = int(self.d.get("ende_weg") or 0) + rest
            self.d["ende_auto"] = True
            self.update_layout()
            PL.layout(tl, self.layout.units)
        if settle:
            self.settle(tl)

    def shot_laenge(self, sid, k, force=False):
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            k = max(1, int(k))
            old_k = int(sh["k"])
            if k == old_k:
                return {"ok": True}
            c = self.clip_by_name()[sh["clip"]]
            xf = self.xf()
            # neue Dauer an dieser Stelle im Raster
            u0 = sh["u0"]
            units = self.layout.units
            new_dur = units[min(len(units) - 1, u0 + k)] - units[u0]
            trial = dict(sh, dur=new_dur)
            src = sh["src"]
            if src + new_dur + xf / 2 > c.dur - PL.EDGE:
                src = c.dur - PL.EDGE - xf / 2 - new_dur
            if src - xf / 2 < PL.EDGE:
                return {"ok": False, "fehler": _t("Der Clip ist für diese Länge zu kurz.")}
            trial["src"] = src
            block = PL.blocked_by(tl, trial, src, xf)
            if block and not force:
                # erst versuchen, nach vorn auszuweichen
                rg = PL.slip_range(tl, trial, c, xf)
                if rg["lo"] <= rg["hi"]:
                    src = float(np.clip(src, rg["lo"], rg["hi"]))
                    trial["src"] = src
                    block = PL.blocked_by(tl, trial, src, xf)
                if block:
                    return {"ok": False, "kollision": [{"id": b["id"], "tl": round(b["tl0"], 2)} for b in block]}
            sh["k"], sh["src"], sh["lock"], sh["t_edit"] = k, round(src, 3), True, time.time()
            self._fix_bis(tl, tl.index(sh))
            for b in block:
                if b in tl:
                    tl.remove(b)
            # Ausgleich: zusätzliche Einheiten bei ungesperrten Schnitten derselben/benachbarter Szenen abziehen
            delta = sum(int(s["k"]) for s in tl) - (len(units) - 1)
            if delta > 0:
                zid = sh.get("szene")
                pos = tl.index(sh)
                rem = self._platz_schaffen(tl, delta, [sh], key=lambda s: (s.get("szene") != zid,
                                                                                   abs(tl.index(s) - pos), s.get("score", 0)))
                if rem > 0:   # alles andere gesperrt: dann eben nur so viel länger, wie Platz ist
                    sh["k"] = max(1, int(sh["k"]) - rem)
            if delta < 0:
                self._fill(tl)
            sh.pop("_fix", None)
            self._resort_scene(tl, sh.get("szene"), auch_fertig=True)
            self._markiere_fix(tl)
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def shot_move(self, sid, index):
        with self.lock:
            sh, tl = self.find_shot(sid)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            tl.remove(sh)
            index = int(np.clip(index, 0, len(tl)))
            tl.insert(index, sh)
            sh["lock"] = True
            sh["manuell"] = True
            sh["t_edit"] = time.time()
            self._fix_bis(tl, tl.index(sh))
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def shot_anders(self, sid):
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            clips = self._chrono_clips(tl, sh.get("szene"), self.scene_clips(sh.get("szene")), tl.index(sh), ausser=sh)
            best = PL.best_free_window(tl, sh, clips, self.xf(), slack=self._slack(sh))
            if not best:
                return {"ok": False, "fehler": _t("In dieser Szene ist keine andere freie Stelle mehr.")}
            sh["clip"], sh["src"], sh["lock"], sh["t_edit"] = best[1], round(best[2], 3), True, time.time()
            sh.pop("_fix", None)
            self._resort_scene(tl, sh.get("szene"), auch_fertig=True)
            self._markiere_fix(tl)
            self._fix_bis(tl, tl.index(sh))
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def szenen_clips(self, sid):
        """Für „weiteren Clip danach einfügen“: alle Clips der Szene dieses Schnitts, mit freier Stelle oder nicht."""
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            k = int(self.d["schnitt"].get("k") or 0) or self.k_default()
            proto = {"id": "neu", "clip": "", "src": 0.0, "dur": self.layout.unit_len() * k, "k": k}
            out = []
            for c in self.scene_clips(sh.get("szene")):
                cand = PL.best_free_window(tl, proto, [c], self.xf(), slack=self._slack(proto))
                out.append({"name": c.name, "dauer": round(c.dur, 1), "bild": self.thumb(c, (cand[2] + proto["dur"] / 2)
                                                                                       if cand else c.dur / 2),
                            "im_film": sum(1 for s in tl if s["clip"] == c.name), "frei": bool(cand),
                            "zeit": c.start.strftime("%H:%M") if c.start else ""})
            return {"szene": sh.get("szene"), "clips": out}

    def shot_einfuegen(self, sid, clip=None):
        """Einen weiteren Ausschnitt aus derselben Szene direkt hinter diesem Schnitt einfügen (gesperrt). Platz dafür
        machen ungesperrte Schnitte anderer Szenen (die Szene bekommt also mehr Zeit); die Filmlänge bleibt."""
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            zid = sh.get("szene")
            clips = self.scene_clips(zid)
            if clip:
                clips = [c for c in clips if c.name == clip]
            k = int(self.d["schnitt"].get("k") or 0) or self.k_default()
            proto = {"id": "neu", "clip": "", "src": 0.0, "dur": self.layout.unit_len() * k, "k": k}
            cand = PL.best_free_window(tl, proto, clips, self.xf(), slack=self._slack(proto))
            if not cand:
                return {"ok": False, "fehler": _t("In diesem Clip ist keine freie Stelle mehr.") if clip
                        else _t("In dieser Szene ist keine freie Stelle mehr.")}
            new = {"id": PL.new_id(), "clip": cand[1], "src": round(cand[2], 3), "k": k, "lock": True, "manuell": True,
                   "szene": zid, "t_edit": time.time()}
            vorher = (self.clean_timeline(tl), self.d.get("fertig_bis"))
            tl.insert(tl.index(sh) + 1, new)
            sh["lock"] = True        # der Schnitt davor bleibt mit stehen – die beiden gehören jetzt zusammen
            self._fix_bis(tl, tl.index(new))
            delta = sum(int(s["k"]) for s in tl) - (len(self.layout.units) - 1)
            if delta > 0:
                rem = self._platz_schaffen(tl, delta, [sh, new], key=lambda s: (s.get("szene") == zid, s.get("score", 0)))
                if rem > 0:
                    self.d["timeline"], self.d["fertig_bis"] = vorher
                    return {"ok": False, "fehler": _t("Kein Platz: Alle anderen Schnitte sind gesperrt.")}
            if delta < 0:
                self._fill(tl, settle=False)
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True, "id": new["id"]}

    AUSGLEICH = ("rest", "nachbar", "kuerzer")
    AEHNLICH_RAND = 3.0   # so weit um einen gelöschten Ausschnitt herum (in derselben Einstellung) nicht nachrücken

    def _aehnlich(self, c, sh):
        """Bereich um einen gelöschten Ausschnitt, der für die Automatik gesperrt wird: dieselbe Einstellung
        (Perspektive) bis zu AEHNLICH_RAND Sekunden davor und danach – damit nichts fast Gleiches nachrückt."""
        a, b = sh["src"], sh["src"] + sh["dur"]
        mid = (a + b) / 2
        seg = next((g for g in (c.segs or []) if g["t0"] <= mid <= g["t1"]), None)
        lo, hi = (seg["t0"], seg["t1"]) if seg else (a, b)
        return round(max(lo, a - self.AEHNLICH_RAND, 0.0), 2), round(min(hi, b + self.AEHNLICH_RAND, c.dur), 2)

    def _entfernen(self, tl, sh, ausgleich, log):
        """Schnitt raus, die Schnitte dahinter rücken nach. Die freien Einheiten: „rest“ = auf die Kategorien dahinter
        verteilen, „nachbar“ = die folgenden Schnitte länger, „kuerzer“ = Film (Musik) am Ende entsprechend kürzer.
        Gibt die Einheiten zurück, die sich nicht unterbringen ließen."""
        idx = tl.index(sh)
        if sh["id"] == self.d.get("fertig_bis"):     # Markierung lag auf dem gelöschten: eins davor
            self.d["fertig_bis"] = tl[idx - 1]["id"] if idx > 0 else None
        tl.remove(sh)
        self._fix_bis(tl, idx - 1)                 # alles vor der gelöschten Stelle ist jetzt fertig
        PL.layout(tl, self.layout.units)
        frei = int(sh["k"])
        if ausgleich == "kuerzer":
            return 0
        if ausgleich == "nachbar":
            cands = [x for x in tl[idx:] if not self.fest(x)]
            vor = frei
            frei = self._laenger(tl, frei, cands, gleichmaessig=False)
            if vor > frei:
                log.append({"art": "nachbar", "n": vor - frei})
        if frei > 0:
            frei = self._zuteilen(tl, frei, ab=idx, log=log)
        return frei

    def entfernen_optionen(self, sid):
        """Für den Dialog beim Entfernen: Was passiert bei welcher Wahl, und was geht gar nicht?"""
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            c = self.clip_by_name()[sh["clip"]]
            bereich = self._aehnlich(c, sh)
            c.excl.append(bereich)
            fid = self.d.get("fertig_bis")
            out = {}
            try:
                for art in ("nachbar", "rest"):
                    t2 = copy.deepcopy(tl)
                    log = []
                    rest = self._entfernen(t2, next(x for x in t2 if x["id"] == sid), art, log)
                    self.d["fertig_bis"] = fid
                    out[art] = {"ok": rest == 0, "log": log}
            finally:
                c.excl.remove(bereich)
                self.d["fertig_bis"] = fid
                self._markiere_fix(tl)
            N = len(self.layout.units) - 1
            sek = round(sh["dur"], 1)
            out["kuerzer"] = {"ok": N - int(sh["k"]) > 8, "sekunden": sek}
            out["takte"] = int(sh["k"])
            out["sekunden"] = sek
            return out

    def shot_entfernen(self, sid, sperren_stelle=True, ausgleich="rest"):
        ausgleich = ausgleich if ausgleich in self.AUSGLEICH else "rest"
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                raise RuntimeError(_t("Schnitt nicht gefunden"))
            if sperren_stelle:   # die Stelle (und fast Gleiches daneben) soll nicht wieder automatisch gewählt werden
                c = self.clip_by_name()[sh["clip"]]
                u = self.d["clips"].setdefault(sh["clip"], {})
                u.setdefault("aus", []).append(list(self._aehnlich(c, sh)))
                self.apply_user_clip_settings()
            log = []
            rest = self._entfernen(tl, sh, ausgleich, log)
            if rest > 0 and ausgleich != "kuerzer":
                self._fill(tl, settle=False)     # notfalls endet die Musik entsprechend früher
                rest = 0
            if ausgleich == "kuerzer":
                self.d["ende_weg"] = int(self.d.get("ende_weg") or 0) + int(sh["k"])
                self.d["ende_auto"] = False
                self.update_layout()
                PL.layout(tl, self.layout.units)
                rest = (len(self.layout.units) - 1) - sum(int(x["k"]) for x in tl)
                if rest > 0:
                    rest = self._zuteilen(tl, rest)
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True, "rest": rest, "log": log}

    def ende_zuruecknehmen(self):
        """„Film kürzer“ aus der Timeline rückgängig: die Musik läuft wieder bis zu ihrem Ende, die freien Takte werden
        hinter „fertig bis hier“ verteilt."""
        with self.lock:
            self.d["ende_weg"] = 0
            self.d["ende_auto"] = False
            self.update_layout()
            tl, _ = self.relayout()
            self._fill(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def shot_sperren(self, sid, lock):
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh:
                sh["lock"] = bool(lock)
                sh["t_edit"] = time.time()
                if not lock and sh.pop("manuell", None):
                    self._resort_scene(tl, sh.get("szene"), auch_fertig=True)   # Automatik darf wieder: zurück in die Zeitfolge
                    self.settle(tl)
                self.d["timeline"] = self.clean_timeline(tl)
                self.save()
            return {"ok": sh is not None}

    def auffuellen(self):
        with self.lock:
            tl, diff = self.relayout()
            if diff > 0:   # Überhang: ungesperrte Schnitte am Ende entfernen
                self._platz_schaffen(tl, diff, [], key=lambda s: -tl.index(s))
            self._fill(tl)
            self.settle(tl)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    # ------------------------------------------------------------------ Export
    def export_job(self, job, formate, kdenlive=True):
        from . import export as EX
        from .util import tools_status
        self.export_dir.mkdir(parents=True, exist_ok=True)
        base = safe_name(self.d["name"])
        outs = []
        n = len(formate) + (1 if kdenlive else 0)
        k = 0
        if kdenlive:
            job.text = _t("Schreibe Kdenlive-Projekt …")
            p = self.export_dir / f"{base}.kdenlive"
            EX.write_project(self, p)
            outs.append(str(p))
            k += 1
            job.fortschritt = k / n
        melt_ok = tools_status().get("melt")
        for fmt in formate:
            F = EX.FORMATE[fmt]
            out = self.export_dir / f"{base}_{fmt}.{F['ext']}"
            job.text = _t("Rendere {label} …", label=_t(F["label"]))

            def prog(f, k=k):
                job.fortschritt = (k + f) / n
                job.text = _t("Rendere {label} … {p} %", label=_t(F["label"]), p=int(f * 100))
            done = False
            if melt_ok:
                xml = self.dirs["tmp"] / f"render_{fmt}.mlt"
                try:
                    EX.write_project(self, xml, F["W"], F["H"], mit_marker=False)
                    EX.render_melt(xml, out, fmt, prog)
                    done = True
                except Exception as e:
                    log(_t("melt: {e} – nehme ffmpeg (ohne Überblendungen)", e=e))
            if not done:
                EX.render_ffmpeg(self, out, fmt, prog)
            outs.append(str(out))
            k += 1
            job.fortschritt = k / n
        self.d["exporte"] = outs
        self.save()
        job.text = _t("Fertig: {files}", files=", ".join(Path(o).name for o in outs))

    # ------------------------------------------------------------------ Originalton
    MUSIK_RAND = 2.0   # so viele Sekunden vor/nach dem Ausschnitt darf im Clip auch keine Musik laufen

    def atmo_plan(self, shots):
        """Originalton für stimmungsvolle Stellen (Lachen, Applaus, Jubel, Menschengruppen) – nie, wo im Clip Musik
        läuft (auch nicht kurz davor oder danach, z. B. bei Proben und Konzerten). Je Clip lässt sich der Originalton
        bevorzugen („an“) oder ausschließen („aus“); Musik schließt ihn immer aus."""
        mode = self.d["schnitt"].get("originalton", "auto")
        for s in shots:
            s["atmo"] = None
            s["ton_info"] = {"grund": "aus_gesamt"} if mode == "aus" else {}
        if mode == "aus":
            return 0
        cl = self.clip_by_name()

        def want(s):
            """Originalton für diesen Schnitt: Schnitt-Einstellung (Timeline) vor Clip-Einstellung (Videos)."""
            return s.get("ton") or cl[s["clip"]].ton or ""
        info = {}
        for s in shots:
            c = cl[s["clip"]]
            if want(s) == "aus":
                info[s["id"]] = None
                s["ton_info"] = {"grund": "aus_schnitt" if s.get("ton") == "aus" else "aus_clip"}
                continue
            kt = self.cache["ton"].get(c.key)
            w = audio_window(c, s["src"], s["src"] + s["dur"], kt)
            if w:
                rand = audio_window(c, s["src"] - self.MUSIK_RAND, s["src"] + s["dur"] + self.MUSIK_RAND, kt)
                w["musik"] = max(w["musik"], rand["musik"] if rand else 0.0)
            info[s["id"]] = w
            if not w:
                s["ton_info"] = {"grund": "kein_ton"}
            elif w["musik"] >= 0.35:
                s["ton_info"] = {"grund": "musik"}
        cands = []
        groups = []
        for s in shots:
            if groups and groups[-1][0].get("szene") == s.get("szene"):
                groups[-1].append(s)
            else:
                groups.append([s])
        for g in groups:
            # „an“ im Schnitt (Timeline) gilt auch, wo im Video Musik läuft – das ist dann deine Entscheidung
            el = [s for s in g if info[s["id"]] and (s.get("ton") == "an"
                                                      or (info[s["id"]]["musik"] < 0.35 and info[s["id"]]["db"] >= -50))]
            if not el:
                continue
            score = max(info[s["id"]]["ereignis"] for s in el)
            forced = any(want(s) == "an" for s in el)
            if forced:
                el = [s for s in el if want(s) == "an" or info[s["id"]]["ereignis"] >= 0.4]
            if score >= 0.4 or forced:
                cands.append((score + (10.0 if forced else 0.0), el))
        cands.sort(key=lambda x: -x[0])
        limit = max(10, sum(1 for sc, _ in cands if sc >= 10.0))
        for sid, (_, el) in enumerate(cands[:limit]):
            gains = [float(np.clip(-26.0 - info[s["id"]]["db"], -14, 6)) for s in el]
            gm = float(np.median(gains))
            for s, gn in zip(el, gains):
                s["atmo"] = {"gain_db": round(float(np.clip(gn, gm - 3, gm + 3)), 1), "gruppe": sid,
                             "art": info[s["id"]]["art"]}
        for s in shots:
            if s["atmo"]:
                s["ton_info"] = {"grund": "dabei", "musik": bool(info[s["id"]]["musik"] >= 0.35)}
            elif not s["ton_info"]:
                s["ton_info"] = {"grund": "unauffaellig"}
        return len(cands[:limit])

    def shot_ton(self, sid, ton):
        """Originalton eines einzelnen Schnitts: "" automatisch, "an", "aus". Wird gesperrt (bleibt beim Neuplanen)."""
        ton = ton if ton in ("an", "aus") else ""
        with self.lock:
            tl, _ = self.relayout()
            sh = next((s for s in tl if s["id"] == sid), None)
            if sh is None:
                return {"ok": False}
            if ton:
                sh["ton"] = ton
                sh["lock"] = True
                sh["t_edit"] = time.time()
                self._fix_bis(tl, tl.index(sh))
            else:
                sh.pop("ton", None)
            self.d["timeline"] = self.clean_timeline(tl)
            self.save()
            return {"ok": True}

    def absenkung_db(self):
        """Wie weit die Musik unter dem Originalton leiser wird (0 = gar nicht)."""
        s = self.d["schnitt"]
        if s.get("originalton", "auto") == "aus":
            return 0.0
        return float(np.clip(float(s.get("absenken", 5) or 0), 0, 18))


def audio_window(c, t0, t1, ki_ton=None):
    res = {"musik": 0.0, "ereignis": 0.0, "art": "", "db": -90.0}
    a = c.ana.get("ton") if c.ana else None
    if not c.has_audio or not a:
        return None
    t = np.array(a["t"])
    m = (t >= t0) & (t <= t1)
    if m.any():
        dbs = np.array(a["db"])[m]
        res["db"] = float(np.percentile(dbs, 80))
        res["musik"] = float(np.array(a["musik"])[m].mean())
        from .util import smoothstep
        nz = float(np.percentile(np.array(a["rauschen"])[m] * smoothstep(dbs, -38, -22), 75))
        res["ereignis"], res["art"] = nz, "gruppe"
    if ki_ton:
        st = np.array(ki_ton["t"])
        w = ki_ton.get("fenster", 10.0)
        m = (st < t1) & (st + w > t0)
        if m.any():
            res["musik"] = max(res["musik"] * 0.3, float(np.array(ki_ton["musik"])[m].max()))
            best, art = 0.0, ""
            for g in ("applaus", "lachen", "jubel", "gruppe"):
                v = float(np.array(ki_ton[g])[m].max()) * (0.8 if g == "gruppe" else 1.0)
                if v > best:
                    best, art = v, g
            res["ereignis"], res["art"] = best, art
    return res
