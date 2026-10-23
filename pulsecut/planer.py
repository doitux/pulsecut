"""Schnittplanung auf dem Musikraster.

Harte Regeln (werden bei jeder Änderung geprüft):
  • Ausschnitte desselben Clips überlappen sich nie (auch nicht mit den Überblend-Rändern), Mindestabstand GAP.
  • Innerhalb einer Szene läuft alles chronologisch (Clips nach Aufnahmebeginn, je Clip von vorne nach hinten),
    außer die Option „Kamerabewegung vor Chronologie“ ist an oder der Benutzer hat selbst umsortiert.
Weiche Ziele: gute Bildqualität, verschiedene Perspektiven, wechselnde/gegenläufige Kamerabewegung,
Stichwort-Gewichte und Szenen-Mengen, Passung zum Stichwort (KI).
"""
import itertools
import math
import uuid

import numpy as np

from .i18n import L as _t
from .video import motion_contrast, motion_label, window_motion, window_score, seg_at

GAP = 0.3                # Mindestabstand zwischen zwei Ausschnitten desselben Clips (s)
EDGE = 0.08              # Abstand zum Clip-Anfang/-Ende
MAX_PER_CLIP = 3
MENGE = {"raus": 0.0, "vielweniger": 0.25, "weniger": 0.55, "": 1.0, "mehr": 1.7, "viel": 2.5}


def new_id():
    return uuid.uuid4().hex[:8]


# ═════════════════════════════════════════════ Hilfen für Ausschnitte

def reserved(sh, xf):
    """Belegter Bereich eines Schnitts im Clip (sichtbar + Überblendränder)."""
    return sh["src"] - xf / 2, sh["src"] + sh["dur"] + xf / 2


def fits_clip(c, src, dur, xf, tol=2e-3):
    return src - xf / 2 >= EDGE - tol and src + dur + xf / 2 <= c.dur - EDGE + tol


def hits_excl(c, a, b, pad=0.15):
    return any(a < eb + pad and b > ea - pad for ea, eb in c.excl)


def overlaps(a0, a1, b0, b1, gap=GAP):
    return a0 < b1 + gap and a1 > b0 - gap


def layout(timeline, units):
    """Schnitte nacheinander aufs Raster legen: Schnitt i belegt k Raster-Einheiten."""
    N = len(units) - 1
    u = 0
    for sh in timeline:
        sh["u0"] = u
        u1 = u + max(1, int(sh["k"]))
        if u >= N:
            sh["tl0"] = sh["tl1"] = units[-1]
            sh["dur"] = 0.0
            sh["ueber"] = True
        else:
            sh["tl0"], sh["tl1"] = units[u], units[min(N, u1)]
            sh["dur"] = sh["tl1"] - sh["tl0"]
            sh["ueber"] = u1 > N
        u = u1
    return u - N   # >0 Überhang, <0 Lücke (in Einheiten)


def check(timeline, clips, xf, allow_unchrono=False):
    """Harte Regeln prüfen. Gibt Liste von Problemen zurück."""
    probs = []
    by = {}
    for sh in timeline:
        by.setdefault(sh["clip"], []).append(sh)
    for name, lst in by.items():
        c = clips.get(name)
        if c is None:
            probs.append({"art": "fehlt", "ids": [s["id"] for s in lst], "text": _t("Clip {name} fehlt", name=name)})
            continue
        lst = sorted(lst, key=lambda s: s["src"])
        for s in lst:
            if s["dur"] > 0 and not fits_clip(c, s["src"], s["dur"], xf):
                probs.append({"art": "rand", "ids": [s["id"]], "text": _t("{name}: Ausschnitt ragt über das Clip-Ende", name=name)})
        for a, b in zip(lst, lst[1:]):
            if a["dur"] > 0 and b["dur"] > 0 and overlaps(*reserved(a, xf), *reserved(b, xf), gap=GAP - 1e-3):
                probs.append({"art": "ueberlappung", "ids": [a["id"], b["id"]],
                              "text": _t("{name}: zwei Ausschnitte überlappen sich", name=name)})
    if not allow_unchrono:
        last = {}
        for sh in timeline:
            if sh.get("manuell"):
                continue
            z = sh.get("szene")
            c = clips.get(sh["clip"])
            if c is None:
                continue
            key = (c.start, c.idx, sh["src"])
            if z in last and key < last[z][0]:
                probs.append({"art": "chronologie", "ids": [last[z][1], sh["id"]],
                              "text": _t("Reihenfolge innerhalb der Szene nicht chronologisch")})
            last[z] = (key, sh["id"])
    return probs


# ═════════════════════════════════════════════ Planer

class Planer:
    def __init__(self, scenes, clips_by_name, units, k=2, xf=0.0, gewichte=None, bewegung_vor_chrono=False,
                 kw_bonus=None):
        self.scenes = scenes                 # Filmreihenfolge, je {id, kw, clips, menge}
        self.clips = clips_by_name
        self.units = list(units)
        self.N = len(units) - 1
        self.k = max(1, int(k))
        self.xf = float(xf)
        self.w = gewichte or {}
        self.bewegung = bool(bewegung_vor_chrono)
        self.kw_bonus = kw_bonus or {}       # clip.key → Array (0,25-s-Raster) Passung zum Stichwort
        self.warn = []

    # ---------------------------------------------------------- Menge und Material
    def usable(self, c, m):
        return c.prio != "raus" and c.segs and (m > 0 or c.prio == "hoch") and c.dur > 1.2

    def per_clip(self, c, m):
        return MAX_PER_CLIP + (1 if c.prio == "hoch" else 0) + (1 if m >= 1.7 else 0) + (1 if m >= 2.5 else 0)

    def L_of(self, nunits):
        u = np.diff(self.units)
        return float(np.median(u)) * nunits if len(u) else 2.0 * nunits

    def capacity(self, z, L):
        m = MENGE.get(z.get("menge", ""), 1.0)
        cap = 0
        need = L + self.xf + GAP
        for c in z["clips"]:
            if not self.usable(c, m):
                continue
            free = max(0.0, c.dur - 2 * EDGE - sum(b - a for a, b in c.excl))
            n_fit = int(free // need) if free >= L * 0.98 + self.xf else 0
            good = max(c.good_sec, 0.0)
            n_good = max(1 if good >= 0.5 * L else 0, int(good // need))
            cap += min(self.per_clip(c, m), n_fit, max(n_good, 1 if c.prio == "hoch" and n_fit else 0))
        return cap

    def mass(self, z):
        m = MENGE.get(z.get("menge", ""), 1.0)
        return sum((max(c.good_sec, 0.5) ** 0.5) * (0.35 + c.mean_q) * (1.6 if c.prio == "hoch" else 1.0)
                   for c in z["clips"] if self.usable(c, m))

    # ---------------------------------------------------------- Zuteilung Schnitte je Szene
    def allocate(self, n_free_units, locked_by_scene):
        L = self.L_of(self.k)
        S = max(0, n_free_units // self.k)
        caps, share = {}, {}
        kw_mass = {}
        for z in self.scenes:
            caps[z["id"]] = max(0, self.capacity(z, L) - len(locked_by_scene.get(z["id"], [])))
            kw_mass.setdefault(z["kw"], 0.0)
            kw_mass[z["kw"]] += self.mass(z)
        kw_share = {}
        for kw, M in kw_mass.items():
            kw_share[kw] = float(self.w.get(kw, 1.0)) * (M ** 0.5 if M > 0 else 0.0)
        tot_kw = sum(kw_share.values()) or 1.0
        for z in self.scenes:
            m = MENGE.get(z.get("menge", ""), 1.0)
            Mk = kw_mass[z["kw"]] or 1.0
            share[z["id"]] = kw_share[z["kw"]] / tot_kw * (self.mass(z) * m) / Mk
        # Wasserfüllung mit Kappung durch das vorhandene Material
        alloc = {zid: 0.0 for zid in caps}
        free = {zid for zid in caps if caps[zid] > 0 and share[zid] > 0}
        rest = float(S)
        for _ in range(12):
            if rest <= 1e-6 or not free:
                break
            tot = sum(share[z] for z in free) or 1.0
            capped = set()
            used = 0.0
            for zid in free:
                add = rest * share[zid] / tot
                if alloc[zid] + add >= caps[zid]:
                    used += caps[zid] - alloc[zid]
                    alloc[zid] = caps[zid]
                    capped.add(zid)
                else:
                    alloc[zid] += add
                    used += add
            rest -= used
            free -= capped
            if not capped:
                break
        # ganzzahlig (größte Reste), jede gewünschte Szene mit Material möglichst ≥ 1
        out = {zid: int(math.floor(v)) for zid, v in alloc.items()}
        left = S - sum(out.values())
        order = sorted(alloc, key=lambda z: -(alloc[z] - math.floor(alloc[z])))
        for zid in order:
            if left <= 0:
                break
            if out[zid] < caps[zid]:
                out[zid] += 1
                left -= 1
        want = [z["id"] for z in self.scenes if share[z["id"]] > 0 and caps[z["id"]] > 0 and out[z["id"]] == 0
                and not locked_by_scene.get(z["id"])]
        for zid in sorted(want, key=lambda z: -share[z]):
            donors = [d for d in out if out[d] >= 2]
            if not donors:
                break
            d = max(donors, key=lambda d: out[d] - alloc[d] * 0.5)
            out[d] -= 1
            out[zid] = 1
        if left > 0:
            self.warn.append(_t("Zu wenig brauchbares Material, um die ganze Musik zu füllen."))
        return out

    # ---------------------------------------------------------- Ausschnitte wählen
    def candidates(self, c, L):
        lo, hi = EDGE + self.xf / 2, c.dur - EDGE - self.xf / 2 - L
        if hi < lo:
            return []
        out = []
        kb = self.kw_bonus.get(c.key)
        for st in np.arange(lo, hi + 1e-6, 0.25):
            st = float(st)
            if c.excl and hits_excl(c, st - self.xf / 2, st + L + self.xf / 2):
                continue
            sc = window_score(c, st, L)
            if kb is not None and len(kb):
                i0, i1 = int(st / 0.25), max(int(st / 0.25) + 1, int((st + L) / 0.25))
                sc += 0.08 * float(np.mean(kb[i0:min(i1, len(kb))])) if i0 < len(kb) else 0.0
            out.append((sc, st))
        return out

    def select(self, z, n, Lsel, locked):
        """n neue Ausschnitte (Länge Lsel) für Szene z wählen, ohne Überlappung mit gesperrten Schnitten."""
        m = MENGE.get(z.get("menge", ""), 1.0)
        taken = {}
        for sh in locked:
            taken.setdefault(sh["clip"], []).append(reserved(sh, self.xf))
        cands = []
        for c in z["clips"]:
            if not self.usable(c, m):
                continue
            for sc, st in self.candidates(c, Lsel):
                cands.append([sc, st, c])
        picks = []
        cnt = {}
        seg_used = {}
        for sh in locked:
            cnt[sh["clip"]] = cnt.get(sh["clip"], 0) + 1
        must = [c for c in z["clips"] if c.prio == "hoch" and self.usable(c, m)]
        while len(picks) < n and cands:
            best, bi = None, -1
            for i, (sc, st, c) in enumerate(cands):
                if cnt.get(c.name, 0) >= self.per_clip(c, m):
                    continue
                a, b = st - self.xf / 2, st + Lsel + self.xf / 2
                if any(overlaps(a, b, x0, x1) for x0, x1 in taken.get(c.name, [])):
                    continue
                v = sc * (0.78 ** cnt.get(c.name, 0))
                sg = seg_at(c, st + Lsel / 2)
                if (c.name, sg) in seg_used:
                    far = min(abs(st - t) for t in seg_used[(c.name, sg)])
                    v -= 0.25 if far < 8 else 0.08
                if must and c in must and not cnt.get(c.name):
                    v += 5.0
                if best is None or v > best:
                    best, bi = v, i
            if bi < 0:
                break
            sc, st, c = cands.pop(bi)
            taken.setdefault(c.name, []).append((st - self.xf / 2, st + Lsel + self.xf / 2))
            cnt[c.name] = cnt.get(c.name, 0) + 1
            seg_used.setdefault((c.name, seg_at(c, st + Lsel / 2)), []).append(st)
            picks.append({"clip": c.name, "win": st, "Lsel": Lsel, "score": round(sc, 3)})
        return picks, cands

    def chrono_key(self, sh):
        c = self.clips[sh["clip"]]
        return (c.start, c.idx, sh["src"] if "src" in sh else sh["win"])

    def order_scene(self, shots):
        """Chronologisch; mit Option „Bewegung vor Chronologie“ so umsortiert, dass benachbarte Schnitte
        möglichst gegenläufige/andere Kamerabewegungen haben (Abweichung von der Zeitfolge kostet etwas)."""
        shots = sorted(shots, key=self.chrono_key)
        if not self.bewegung or len(shots) < 3:
            return shots
        mv = [window_motion(self.clips[s["clip"]], s.get("src", s.get("win")), s.get("Lsel", s.get("dur", 2.0)))
              for s in shots]
        n = len(shots)

        def cost(perm):
            con = sum(motion_contrast(mv[perm[i]], mv[perm[i + 1]]) for i in range(n - 1))
            inv = sum(1 for i in range(n) for j in range(i + 1, n) if perm[i] > perm[j])
            return con - 0.12 * inv

        if n <= 7:
            best = max(itertools.permutations(range(n)), key=cost)
        else:
            best = list(range(n))
            improved = True
            while improved:
                improved = False
                for i in range(n - 1):
                    t = best[:]
                    t[i], t[i + 1] = t[i + 1], t[i]
                    if cost(t) > cost(best) + 1e-9:
                        best, improved = t, True
        res = [shots[i] for i in best]
        for i, s in enumerate(res):
            if best[i] != i:
                s["bewegung_umsortiert"] = True
        return res

    def refine_motion(self, scene_shots, cands_by_scene):
        """Chronologisch geordnete Schnitte: nahe Alternativen wählen, wenn dadurch die Kamerabewegung zum
        Vorgänger/Nachfolger abwechslungsreicher wird (Qualität ≥ 85 %)."""
        for zid, shots in scene_shots.items():
            for i, s in enumerate(shots):
                if s.get("lock") or "win" not in s:
                    continue
                c = self.clips[s["clip"]]
                L = s["Lsel"]
                nb = [x for x in (shots[i - 1] if i else None, shots[i + 1] if i + 1 < len(shots) else None) if x]
                if not nb:
                    continue

                def mot(x):
                    return window_motion(self.clips[x["clip"]], x.get("win", x.get("src")), x.get("Lsel", 2.0))

                def contrast(st):
                    v = window_motion(c, st, L)
                    return sum(motion_contrast(v, mot(x)) for x in nb) / len(nb)

                cur = contrast(s["win"])
                same = [(x.get("win", x.get("src")), x.get("Lsel", x.get("dur", L))) for x in shots
                        if x is not s and x["clip"] == s["clip"]]
                lo = max([w + lx + self.xf + GAP for w, lx in same if w < s["win"]] or [-1e9])
                hi = min([w - L - self.xf - GAP for w, lx in same if w > s["win"]] or [1e9])
                best = None
                for sc, st, cc in cands_by_scene.get(zid, []):
                    if cc is not c or abs(st - s["win"]) > 6 or not (lo <= st <= hi) or sc < 0.85 * s["score"]:
                        continue
                    g = contrast(st)
                    if g > cur + 0.2 and (best is None or g > best[0]):
                        best = (g, st, sc)
                if best:
                    s["win"], s["score"] = best[1], round(best[2], 3)

    # ---------------------------------------------------------- Gesamtplan
    def plan(self, locked=None):
        locked = [dict(s) for s in (locked or []) if s["clip"] in self.clips]
        for s in locked:
            s.setdefault("dur", self.L_of(int(s["k"])))
        scene_ids = {z["id"] for z in self.scenes}
        by_scene = {}
        for s in locked:
            if s.get("szene") not in scene_ids:   # Szene gibt es nicht mehr → Szene des Clips suchen
                s["szene"] = next((z["id"] for z in self.scenes if any(c.name == s["clip"] for c in z["clips"])), None)
            if s["szene"]:
                by_scene.setdefault(s["szene"], []).append(s)
        locked_units = sum(int(s["k"]) for lst in by_scene.values() for s in lst)
        free_units = max(0, self.N - locked_units)
        alloc = self.allocate(free_units, by_scene)
        timeline = []
        for _round in range(3):
            # Skelett: Anzahl je Szene → größte mögliche Dauer im Bereich der Szene
            u = 0
            scene_span = {}
            for z in self.scenes:
                n_l = len(by_scene.get(z["id"], []))
                ku = alloc.get(z["id"], 0) * self.k + sum(int(s["k"]) for s in by_scene.get(z["id"], []))
                scene_span[z["id"]] = (u, u + ku)
                u += ku
            scene_shots, cands_by = {}, {}
            achieved = {}
            for z in self.scenes:
                a, b = scene_span[z["id"]]
                n = alloc.get(z["id"], 0)
                if n <= 0 and not by_scene.get(z["id"]):
                    continue
                Lmax = 0.0
                for uu in range(a, max(a + 1, b - self.k + 1)):
                    if uu + self.k <= len(self.units) - 1:
                        Lmax = max(Lmax, self.units[uu + self.k] - self.units[uu])
                Lmax = Lmax or self.L_of(self.k)
                picks, rest = self.select(z, n, Lmax + 0.02, by_scene.get(z["id"], []))
                for p in picks:
                    p.update({"id": new_id(), "k": self.k, "lock": False, "szene": z["id"]})
                achieved[z["id"]] = len(picks)
                cands_by[z["id"]] = rest
                scene_shots[z["id"]] = picks + [dict(s) for s in by_scene.get(z["id"], [])]
            missing = sum(max(0, alloc.get(zid, 0) - achieved.get(zid, 0)) for zid in alloc)
            if missing == 0 or _round == 2:
                break
            # nicht erreichte Schnitte auf Szenen mit Reserve verteilen
            for zid in alloc:
                alloc[zid] = achieved.get(zid, 0)
            spare = [z for z in self.scenes if len(cands_by.get(z["id"], [])) > 0]
            spare.sort(key=lambda z: -self.mass(z) * MENGE.get(z.get("menge", ""), 1.0) * self.w.get(z["kw"], 1.0))
            i = 0
            while missing > 0 and spare:
                alloc[spare[i % len(spare)]["id"]] += 1
                missing -= 1
                i += 1
                if i > 4 * len(spare) + 50:
                    break
        # Reihenfolge je Szene, Bewegung verfeinern, dann aufs Raster legen
        for zid in scene_shots:
            scene_shots[zid] = self.order_scene(scene_shots[zid])
        if not self.bewegung:
            self.refine_motion(scene_shots, cands_by)
            for zid in scene_shots:
                scene_shots[zid] = sorted(scene_shots[zid], key=self.chrono_key)
        for z in self.scenes:
            timeline += scene_shots.get(z["id"], [])
        # Einheiten genau füllen: fehlende Einheiten auf Schnitte mit Platz im Clip verteilen
        if distribute_rest(timeline, self.clips, self.units, self.xf) > 0:
            msg = _t("Zu wenig brauchbares Material, um die ganze Musik zu füllen.")
            if msg not in self.warn:
                self.warn.append(msg)
        layout(timeline, self.units)
        for s in timeline:
            c = self.clips[s["clip"]]
            if "win" in s:   # sichtbarer Teil mittig im gewählten Fenster (wurde er länger: ab Fensteranfang)
                L = s.pop("Lsel")
                w = s.pop("win")
                s["src"] = round(float(np.clip(w + max(0.0, L - s["dur"]) / 2,
                                               EDGE + self.xf / 2, c.dur - EDGE - self.xf / 2 - s["dur"])), 3)
        # Zeitfolge je Szene und Clip festhalten, bevor repair() nach Lage im Clip sortiert
        last = {}
        for s in timeline:
            if s.get("manuell"):
                continue
            key = (s.get("szene"), s["clip"])
            if key in last and s["src"] < last[key]:
                s["src"] = round(last[key] + 0.001, 3)
            last[key] = s["src"]
        repair(timeline, self.clips, self.xf)
        for s in timeline:
            s["bewegung"] = motion_label(window_motion(self.clips[s["clip"]], s["src"], max(0.25, s["dur"])))
        return timeline


# ═════════════════════════════════════════════ Reparatur und Bearbeitung

def distribute_rest(timeline, clips, units, xf):
    """Fehlen Raster-Einheiten bis zum Musikende, bekommen Schnitte mit genug Platz im Clip je eine Einheit mehr
    (zuerst der letzte Schnitt, dann von hinten nach vorne). Gerechnet wird mit den echten Taktlängen."""
    N = len(units) - 1
    rest = N - sum(int(s["k"]) for s in timeline)
    if not timeline or rest <= 0:
        return 0

    def room(s, add):
        """Passt der Schnitt mit `add` Einheiten mehr (an seiner Stelle) samt seinen Geschwistern in den Clip?"""
        c = clips[s["clip"]]
        u0 = s.get("u0", 0)
        dur = units[min(N, u0 + int(s["k"]) + add)] - units[min(N, u0)]
        others = sum(x.get("dur", 0) + xf + GAP for x in timeline if x["clip"] == s["clip"] and x is not s)
        return dur + xf + 2 * EDGE + others <= c.dur

    layout(timeline, units)
    last = timeline[-1]
    if rest <= max(1, int(last["k"])) and not (last.get("lock") or last.get("_fix")) and room(last, rest):
        last["k"] = int(last["k"]) + rest
        return 0
    guard = 0
    while rest > 0 and guard < 10 * len(timeline) + 10:
        guard += 1
        progress = False
        for s in reversed(timeline):
            if rest <= 0:
                break
            if s.get("lock") or s.get("_fix") or not room(s, 1):
                continue
            s["k"] = int(s["k"]) + 1
            rest -= 1
            progress = True
            layout(timeline, units)
        if not progress:   # kein Clip hat mehr Platz: Das Material ist aufgebraucht. Die harten Regeln gehen vor,
            break          # der Film wird dann etwas kürzer als die Musik (die Oberfläche weist darauf hin).
    return rest


def repair(timeline, clips, xf):
    """Ausschnitte je Clip so wenig wie möglich verschieben, bis keiner mehr überlappt oder übers Ende ragt.
    (Projektion auf die zulässigen Lagen: Rückwärtslauf für Obergrenzen, Vorwärtslauf für Untergrenzen.)
    Gibt die Clips zurück, in denen es nicht passt (zu viel Material für den Clip)."""
    by = {}
    for sh in timeline:
        if sh["dur"] > 0:
            by.setdefault(sh["clip"], []).append(sh)
    unfit = []
    for name, lst in by.items():
        c = clips[name]
        lst.sort(key=lambda s: s["src"])
        lo0, hi0 = EDGE + xf / 2, c.dur - EDGE - xf / 2
        n = len(lst)
        U = [0.0] * n
        nxt = hi0 + xf + GAP      # Anfang des „nächsten“ jenseits des Endes
        for i in range(n - 1, -1, -1):
            U[i] = nxt - xf - GAP - lst[i]["dur"]
            nxt = U[i]
        if U[0] < lo0 - 1e-6:
            unfit.append(name)
        prev_end = None
        for i, s in enumerate(lst):
            lo = lo0 if prev_end is None else prev_end + xf + GAP
            x = min(max(s["src"], lo), max(lo, U[i]))
            if abs(x - s["src"]) > 1e-4:
                s["src"] = (math.floor(x * 1000) / 1000) if x < s["src"] else (math.ceil(x * 1000) / 1000)
            prev_end = s["src"] + s["dur"]
    return unfit


def neighbors(timeline, sh):
    """Vorheriger und nächster Ausschnitt desselben Clips (nach Lage im Clip)."""
    same = sorted([s for s in timeline if s["clip"] == sh["clip"] and s["id"] != sh["id"] and s["dur"] > 0],
                  key=lambda s: s["src"])
    prev = [s for s in same if s["src"] < sh["src"]]
    nxt = [s for s in same if s["src"] >= sh["src"]]
    return (prev[-1] if prev else None), (nxt[0] if nxt else None)


def slip_range(timeline, sh, c, xf):
    """Erlaubter Bereich für den Anfang des sichtbaren Ausschnitts (feste Länge)."""
    p, n = neighbors(timeline, sh)
    lo = EDGE + xf / 2
    hi = c.dur - EDGE - xf / 2 - sh["dur"]
    lo_n = p["src"] + p["dur"] + xf + GAP if p else lo
    hi_n = n["src"] - xf - GAP - sh["dur"] if n else hi
    return {"min": round(lo, 3), "max": round(hi, 3), "lo": round(max(lo, lo_n), 3), "hi": round(min(hi, hi_n), 3),
            "vor": p["id"] if p else None, "nach": n["id"] if n else None}


def blocked_by(timeline, sh, src, xf):
    """Welche anderen Ausschnitte desselben Clips stünden bei Anfang src im Weg?"""
    a, b = src - xf / 2, src + sh["dur"] + xf / 2
    return [s for s in timeline if s["id"] != sh["id"] and s["clip"] == sh["clip"] and s["dur"] > 0
            and overlaps(a, b, *reserved(s, xf))]


def best_free_window(timeline, sh, scene_clips, xf, planer_like=None, exclude_ids=(), slack=0.15):
    """Bester freier Ausschnitt gleicher Länge in der Szene (für „andere Stelle“ und aufgegebene Nachbarn).
    slack: Reserve, weil sich die Dauer je nach Lage im Raster minimal ändern kann."""
    best = None
    L = sh["dur"] + slack
    for c in scene_clips:
        if c.prio == "raus" or not c.segs:
            continue
        others = [reserved(s, xf) for s in timeline if s["clip"] == c.name and s.get("id") != sh.get("id")
                  and s["dur"] > 0 and s["id"] not in exclude_ids]
        lo, hi = EDGE + xf / 2, c.dur - EDGE - xf / 2 - L
        for st in np.arange(lo, hi + 1e-6, 0.25):
            st = float(st)
            a, b = st - xf / 2, st + L + xf / 2
            if any(overlaps(a, b, x0, x1) for x0, x1 in others) or (c.excl and hits_excl(c, a, b)):
                continue
            if c.name == sh["clip"] and abs(st - sh["src"]) < sh["dur"]:
                continue   # wirklich eine andere Stelle
            sc = window_score(c, st, sh["dur"]) * (0.85 if any(s["clip"] == c.name for s in timeline) else 1.0)
            if best is None or sc > best[0]:
                best = (sc, c.name, st)
    return best
