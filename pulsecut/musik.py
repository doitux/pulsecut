"""Musik: Beat- und Takterkennung, Anordnung der Stücke (direkt/Überblendung, Kürzen), Klick-Spur, Vorschau-Mix."""
import json
import subprocess
from pathlib import Path

import numpy as np

from .i18n import L as _t
from .util import FPS, clean_env, ffmpeg_cmd, md5, run

MUSIC_VERSION = 3
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".aiff", ".aif", ".wma"}


def _dbn_beats(act, fps, bpm_lo=55.0, bpm_hi=215.0, lam_obs=16, lam_t=100.0, quad=3000.0):
    """Beat-Tracking als verstecktes Markov-Modell (Takt-Zeiger-Modell nach Krebs/Böck/Widmer):
    Zustand = (Schlagabstand, Position im Schlag). Tempoänderungen sind nur auf dem Schlag möglich und
    kosten umso mehr, je größer sie sind – sanfte Tempoverläufe werden mitgegangen, Sprünge auf Achtel,
    Triolen oder den Gegenschlag dagegen vermieden."""
    taus = np.arange(int(np.floor(60 * fps / bpm_hi)), int(np.ceil(60 * fps / bpm_lo)) + 1)
    nt = len(taus)
    offs = np.r_[0, np.cumsum(taus)[:-1]]
    S = int(taus.sum())
    prev_idx = np.arange(S) - 1
    start_idx, end_idx = offs, offs + taus - 1
    tau_of = np.repeat(np.arange(nt), taus)
    pos = np.arange(S) - offs[tau_of]
    isbeat = pos < np.maximum(1, taus[tau_of] / lam_obs)
    lr = np.log(taus[:, None] / taus[None, :])
    logA = -lam_t * np.abs(lr) - quad * lr ** 2          # [neu, alt]
    logA = logA - np.log(np.exp(logA).sum(axis=0, keepdims=True))
    a = np.clip(act, 1e-4, 1 - 1e-4)
    la, lna = np.log(a), np.log((1 - a) / (lam_obs - 1))
    v = np.full(S, -np.log(S))
    n = len(act)
    back = np.zeros((n, nt), np.int16)
    ar = np.arange(nt)
    for t in range(n):
        cand = logA + v[end_idx][None, :]
        j = np.argmax(cand, axis=1)
        nv = v[prev_idx]
        nv[start_idx] = cand[ar, j]
        back[t] = j
        nv += np.where(isbeat, la[t], lna[t])
        v = nv - nv.max()
    s = int(np.argmax(v))
    beats = []
    for t in range(n - 1, -1, -1):
        ti = tau_of[s]
        if s == offs[ti]:
            beats.append(t)
            s = int(end_idx[back[t, ti]])
        else:
            s -= 1
    return np.array(beats[::-1], dtype=int)


def _bar_phase(S, meter, jump=20.0):
    """Taktposition je Schlag (Viterbi): Taktanfänge sitzen auf hohen Werten von S; ein Taktsprung
    (eingeschobener/verkürzter Takt) ist erlaubt, kostet aber viel."""
    nb = len(S)
    logT = np.full((meter, meter), -jump)
    for p in range(meter):
        logT[p, (p + 1) % meter] = 0.0
    v = np.zeros(meter)
    v[0] += S[0]
    back = np.zeros((nb, meter), int)
    for i in range(1, nb):
        cand = v[:, None] + logT
        back[i] = np.argmax(cand, axis=0)
        v = cand.max(axis=0)
        v[0] += S[i]
    p = int(np.argmax(v))
    path = [p]
    for i in range(nb - 1, 0, -1):
        p = int(back[i, p])
        path.append(p)
    return np.array(path[::-1])


def analyse_music(path, fix=None):
    """Musik genau vermessen: Schlagspitzen (Onsets), Beats mit Tempoverlauf, Taktart, Taktanfänge
    (Akzente im Bass + Harmoniewechsel), hörbarer Anfang/Ende und eine Lautstärkekurve für die Übersicht.
    fix = Korrekturen aus der Übersicht: bpm (Tempo-Vorgabe), oktave (-1 halb, +1 doppelt), takt (3/4),
    verschiebung (Taktanfang um n Schläge), versatz_ms."""
    fix = fix or {}
    sr, hop, nfft = 22050, 128, 1024
    raw = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
               "-ar", str(sr), "-f", "f32le", "-"], binary=True)
    y = np.frombuffer(raw, np.float32)
    if len(y) < sr * 5:
        raise RuntimeError(_t("Audio zu kurz"))
    nfr = 1 + (len(y) - nfft) // hop
    win = np.hanning(nfft).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    low = freqs < 160
    cb = (freqs >= 55) & (freqs <= 2000)
    pc = np.round(69 + 12 * np.log2(freqs[cb] / 440.0)).astype(int) % 12
    onehot = np.zeros((int(cb.sum()), 12), np.float32)
    onehot[np.arange(len(pc)), pc] = 1
    flux = np.zeros(nfr, np.float32)
    fluxl = np.zeros(nfr, np.float32)
    rms = np.zeros(nfr, np.float32)
    chroma = np.zeros((nfr, 12), np.float32)
    prev = None
    for s0 in range(0, nfr, 1024):
        idx = np.arange(s0, min(nfr, s0 + 1024))
        fr = y[idx[:, None] * hop + np.arange(nfft)[None, :]]
        rms[idx] = np.sqrt((fr ** 2).mean(axis=1))
        mag = np.abs(np.fft.rfft(fr * win, axis=1))
        lm = np.log1p(100 * mag)
        full = np.vstack([(prev if prev is not None else lm[0])[None, :], lm])
        d = np.maximum(0, np.diff(full, axis=0))
        flux[idx] = d.sum(axis=1)
        fluxl[idx] = d[:, low].sum(axis=1)
        chroma[idx] = (mag[:, cb] ** 2) @ onehot
        prev = lm[-1]
    fps = sr / hop

    def norm_env(e):
        k = int(fps * 0.4)
        e = np.maximum(e - np.convolve(e, np.ones(k) / k, mode="same"), 0)
        return e / (e.std() + 1e-9)

    env, envl = norm_env(flux), norm_env(fluxl)
    comb = env + envl                     # Bass/Bassdrum zählt doppelt → sitzt auf dem Schlag, nicht auf dem „und“
    n = len(comb)
    act = np.clip(comb / (np.percentile(comb, 99) + 1e-9), 0, 1) * 0.95
    # Beats (HMM über Tempo und Schlagposition)
    lo_b, hi_b = 55.0, 215.0
    if fix.get("bpm"):
        lo_b, hi_b = float(fix["bpm"]) * 0.88, float(fix["bpm"]) * 1.12
    beats = _dbn_beats(act, fps, lo_b, hi_b)
    if len(beats) < 8:
        raise RuntimeError(_t("kein Rhythmus erkennbar"))

    def peak(sig, x, rad):
        return np.array([max(0, min(n - 1, b - rad)) + int(np.argmax(sig[max(0, b - rad):b + rad + 1])) for b in x])

    # Oktave: Achtel statt Viertel erwischt? (sehr schnell + jeder zweite Schlag klar stärker im Bass)
    bpm0 = 60 * fps / float(np.median(np.diff(beats)))
    sl = np.array([envl[max(0, b - 3):b + 4].max() for b in beats])
    ratio = max(sl[0::2].mean(), sl[1::2].mean()) / (min(sl[0::2].mean(), sl[1::2].mean()) + 1e-9)
    okt = int(fix.get("oktave") or 0)
    if not fix.get("bpm") and okt == 0 and bpm0 > 150 and (ratio > 1.8 or bpm0 > 200):
        okt = -1
    if okt < 0:
        par = 0 if sl[0::2].mean() >= sl[1::2].mean() else 1
        beats = beats[par::2]
    elif okt > 0:
        mids = (beats[:-1] + beats[1:]) // 2
        mids = peak(comb, mids, max(1, int(np.median(np.diff(beats)) / 8)))
        beats = np.sort(np.r_[beats, mids])
    # auf die tatsächliche Schlagspitze verfeinern (±40 ms, Unter-Frame genau)
    rad = int(round(0.04 * fps))
    ref = []
    for b in beats:
        a0, a1 = max(1, b - rad), min(n - 2, b + rad)
        j = a0 + int(np.argmax(env[a0:a1 + 1]))
        if env[j] < 0.2:
            j = int(b)
        y0, y1, y2 = env[j - 1], env[j], env[j + 1]
        den = y0 - 2 * y1 + y2
        off = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) if den < 0 else 0.0
        ref.append(j + off)
    ref = np.array(ref)
    btimes = (ref * hop + nfft / 2) / sr + 0.014 + float(fix.get("versatz_ms") or 0) / 1000.0
    bi = np.clip(np.round(ref).astype(int), 0, n - 1)
    strength = np.array([env[max(0, b - 4):b + 5].max() for b in bi])
    # Lautstärke / hörbarer Bereich: Beats in Stille verwerfen
    rdb = 20 * np.log10(rms + 1e-9)
    thr = rdb.max() - 40
    loud = np.where(rdb > thr)[0]
    start = max(0.0, float(loud[0] * hop / sr) - 0.05) if len(loud) else 0.0
    end = min(len(y) / sr, float((loud[-1] * hop + nfft) / sr) + 0.3) if len(loud) else len(y) / sr
    keep = (btimes >= start - 0.05) & (btimes <= end - 0.2) & (rdb[bi] > rdb.max() - 45)
    btimes, bi, strength = btimes[keep], bi[keep], strength[keep]
    nb = len(bi)
    # Taktart und Taktanfang: Bass-Akzente + Harmoniewechsel + Schlagstärke
    meter = int(fix.get("takt") or 0) if int(fix.get("takt") or 0) in (2, 3, 4) else 0
    down = np.zeros(nb, bool)
    if nb >= 12:
        segs = [(bi[i], bi[i + 1] if i + 1 < nb else min(n, bi[i] + max(1, bi[i] - bi[i - 1]))) for i in range(nb)]
        ch = np.array([chroma[a:max(a + 1, c)].mean(axis=0) for a, c in segs])
        ch = ch / (np.linalg.norm(ch, axis=1, keepdims=True) + 1e-9)
        nov = np.r_[0.0, 1 - (ch[1:] * ch[:-1]).sum(axis=1)]
        lowacc = np.array([envl[max(0, b - 4):b + 5].max() for b in bi])

        def z(x):
            return (x - x.mean()) / (x.std() + 1e-9)

        S = z(lowacc) + z(nov) + 0.5 * z(strength)
        if not meter:
            best = {}
            for m in (4, 3):
                sc = [S[p::m].mean() - S.mean() for p in range(m)]
                best[m] = max(sc)
            meter = 3 if (best[3] > 1.25 * best[4] and best[3] > 0.25) else 4
        down = _bar_phase(S, meter) == 0
    else:
        meter = meter or 4
        down[::meter] = True
    sh = int(fix.get("verschiebung") or 0) % meter
    if sh:
        down = np.roll(down, sh)
    step = max(1, int(round(fps / 10)))
    curve = rms[::step]
    curve = curve / (curve.max() + 1e-9)
    bpm = 60.0 / float(np.median(np.diff(btimes))) if nb > 2 else 120.0
    bars = [float(t) for t, d in zip(btimes, down) if d]
    return {"v": MUSIC_VERSION, "fix": fix, "beats": [round(float(x), 4) for x in btimes],
            "down": [bool(x) for x in down], "staerke": [round(float(x), 2) for x in strength], "takt": meter,
            "bpm": round(float(bpm), 2), "oktave_auto": okt if not fix.get("oktave") else 0,
            "taktlaenge": round(float(np.median(np.diff(bars))) if len(bars) > 2 else meter * 60 / bpm, 3),
            "takte": len(bars), "dur": round(len(y) / sr, 3), "start": round(start, 3), "ende": round(end, 3),
            "kurve": [round(float(x), 3) for x in curve], "kurve_hz": fps / step}


# ═════════════════════════════════════════════ Anordnung der Musikstücke

def downbeats(tr):
    return [b for b, d in zip(tr["beats"], tr["down"]) if d]


def beat_positions(tr):
    """Position jedes Beats im Takt (0 = Taktanfang)."""
    pos, k = [], -1
    for d in tr["down"]:
        k = 0 if d else (k + 1 if k >= 0 else -1)
        pos.append(k)
    return pos


class MusikLayout:
    """Ordnet die Stücke auf der Zeitachse an (direkt hintereinander oder mit Überblendung), kürzt auf Wunsch
    einzelne Stücke vorne oder hinten (immer an einem Taktanfang) und liefert das Schnittraster."""

    def __init__(self, tracks, uebergang="direkt", blende=2.0, ziel=None, kuerzen=None, raster="takt"):
        self.tracks = tracks
        self.xf = float(blende) if uebergang == "blende" else 0.0
        self.ziel = float(ziel) if ziel else None
        self.kuerzen = dict(kuerzen or {})
        self.raster = raster
        self.segments, self.units, self.beats, self.switches = [], [], [], []
        self.info = {}
        self.D = 0.0
        self.compute()

    @staticmethod
    def eff(tr):
        return tr["ende"] - tr["start"]

    def full_length(self):
        n = len(self.tracks)
        return sum(self.eff(t) for t in self.tracks) - self.xf * max(0, n - 1)

    @staticmethod
    def _snap_down(tr, t, lo, hi):
        cand = [b for b in downbeats(tr) if lo <= b <= hi] or [b for b in tr["beats"] if lo <= b <= hi]
        return min(cand, key=lambda b: abs(b - t)) if cand else t

    def compute(self):
        T = self.tracks
        n = len(T)
        full = self.full_length()
        cut = {i: 0.0 for i in range(n)}
        modes = {i: self.kuerzen.get(i, "nein") for i in range(n)}
        auto = False
        need = max(0.0, full - self.ziel) if self.ziel else 0.0
        if need > 1.0:
            trim = [i for i in range(n) if modes[i] in ("vorne", "hinten")]
            if not trim:   # nichts gewählt: längstes Stück hinten kürzen
                i = max(range(n), key=lambda i: self.eff(T[i]))
                modes[i], trim, auto = "hinten", [i], True
            left = need
            for _ in range(3):
                room = {i: max(0.0, self.eff(T[i]) - 20.0 - cut[i]) for i in trim}
                tot = sum(self.eff(T[i]) for i in trim if room[i] > 0.5)
                if left <= 0.5 or tot <= 0:
                    break
                for i in trim:
                    if room[i] > 0.5:
                        add = min(room[i], left * self.eff(T[i]) / tot)
                        cut[i] += add
                left = need - sum(cut.values())
        segs = []
        t = 0.0
        for i, tr in enumerate(T):
            s_in, s_out = tr["start"], tr["ende"]
            fi, fo = (0.0 if i == 0 else 0.03), 0.03
            bar = float(tr.get("taktlaenge") or 2.0)
            if cut[i] > 0.5 and modes[i] == "vorne":
                s_in = self._snap_down(tr, tr["start"] + cut[i], tr["start"], tr["ende"] - 15) - 0.02
                fi = 0.25
            elif cut[i] > 0.5 and modes[i] == "hinten":
                e = self._snap_down(tr, tr["ende"] - cut[i], tr["start"] + 15, tr["ende"])
                s_out = min(tr["ende"], e + 0.3)
                fo = (3.0 if i == n - 1 else float(np.clip(bar, 1.5, 3.0))) + 0.3
            tl = t - (self.xf if i > 0 else 0.0)
            if i > 0 and self.xf > 0:
                fi = max(fi, self.xf)
                segs[-1]["fade_out"] = max(segs[-1]["fade_out"], self.xf)
            segs.append({"track": i, "tl_start": tl, "src_in": max(0.0, s_in), "src_out": s_out,
                         "fade_in": fi, "fade_out": fo, "lane": i % 2, "modus": modes[i], "gekuerzt": cut[i]})
            t = tl + (s_out - max(0.0, s_in))
        for sg in segs:   # Kdenlive setzt Clips auf ganze Videobilder → Raster aus der gerundeten Lage
            sg["tl_start"] = round(sg["tl_start"] * FPS) / FPS
            sg["src_in"] = round(sg["src_in"] * FPS) / FPS
        self.segments = segs
        self.D = segs[-1]["tl_start"] + segs[-1]["src_out"] - segs[-1]["src_in"] if segs else 0.0
        self.switches = [sg["tl_start"] + (self.xf / 2 if self.xf else 0.0) for sg in segs[1:]]
        self._grid()
        self.info = {"voll": round(full, 2), "dauer": round(self.D, 2), "ziel": self.ziel, "noetig": round(need, 2),
                     "auto_gekuerzt": auto, "gekuerzt": {str(i): round(c, 1) for i, c in cut.items() if c > 0.5},
                     "modi": {str(i): m for i, m in modes.items()},
                     "rest": round(max(0.0, need - sum(cut.values())), 1)}

    def _grid(self):
        D = self.D
        units, beats = [], []
        for i, sg in enumerate(self.segments):
            tr = self.tracks[sg["track"]]
            lo = 0.0 if i == 0 else self.switches[i - 1]
            hi = self.switches[i] if i < len(self.switches) else D
            pos = beat_positions(tr)
            meter = int(tr.get("takt") or 4)
            for bt, dn, p in zip(tr["beats"], tr["down"], pos):
                if bt < sg["src_in"] - 0.01 or bt > sg["src_out"]:
                    continue
                t = sg["tl_start"] + (bt - sg["src_in"])
                if lo - 0.05 <= t < hi - 0.05 and 0 <= t < D - 0.3:
                    beats.append(t)
                    if dn or (self.raster == "halbtakt" and meter % 2 == 0 and p == meter // 2):
                        units.append(t)
        units = sorted(set(round(x, 4) for x in units + list(self.switches) if 0.5 < x < D - 0.5))
        clean = [0.0]
        for t in units:
            if t - clean[-1] >= 0.5:
                clean.append(t)
        if D - clean[-1] < 0.5 and len(clean) > 1:
            clean.pop()
        self.units = clean + [D]
        self.beats = sorted(beats)

    def unit_len(self):
        u = np.diff(self.units)
        return float(np.median(u)) if len(u) else 2.0

    def curve(self, step=0.2):
        pts = {}
        for s in self.segments:
            tr = self.tracks[s["track"]]
            k, hz = tr.get("kurve") or [], tr.get("kurve_hz", 10)
            t = s["src_in"]
            while t < s["src_out"] and k:
                ft = round((s["tl_start"] + t - s["src_in"]) / step) * step
                if 0 <= ft <= self.D:
                    v = k[min(len(k) - 1, int(t * hz))]
                    pts[ft] = max(pts.get(ft, 0), v)
                t += step
        return [[round(t, 2), round(v, 3)] for t, v in sorted(pts.items())]

    def signature(self):
        return md5(json.dumps([[self.tracks[s["track"]].get("key", ""), round(s["tl_start"], 3), round(s["src_in"], 3),
                                round(s["src_out"], 3), round(s["fade_in"], 2), round(s["fade_out"], 2)]
                               for s in self.segments]))

    def ffmpeg_mix_args(self, D=None):
        """Eingänge und Filter, die die Musik genau wie im Film zusammensetzen."""
        D = D or self.D
        ins, fl = [], []
        for k, sg in enumerate(self.segments):
            tr = self.tracks[sg["track"]]
            ins += ["-i", tr["path"]]
            dur = sg["src_out"] - sg["src_in"]
            f = f"[{k}:a]atrim={sg['src_in']:.3f}:{sg['src_out']:.3f},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo"
            if sg["fade_in"] > 0:
                f += f",afade=t=in:d={sg['fade_in']:.2f}"
            if sg["fade_out"] > 0:
                f += f",afade=t=out:st={max(0, dur - sg['fade_out']):.3f}:d={sg['fade_out']:.2f}"
            ms = int(round(sg["tl_start"] * 1000))
            f += f",adelay={ms}|{ms}[m{k}]"
            fl.append(f)
        nm = len(self.segments)
        fl.append("".join(f"[m{k}]" for k in range(nm)) + f"amix=inputs={nm}:normalize=0:duration=longest,"
                  f"atrim=0:{D:.3f}[musik]")
        return ins, fl


def audio_codec_args():
    enc = run(["ffmpeg", "-hide_banner", "-encoders"], check=False)
    if "libopus" in enc:
        return ["-c:a", "libopus", "-b:a", "128k"], "ogg"
    return ["-c:a", "libvorbis", "-q:a", "4"], "ogg"


def render_music_mix(layout, out):
    """Musik wie im Film als eine Datei (für die Live-Vorschau)."""
    ins, fl = layout.ffmpeg_mix_args()
    ca, _ = audio_codec_args()
    tmp = Path(str(out) + ".tmp.ogg")
    run(ffmpeg_cmd() + ["-y"] + ins + ["-filter_complex", ";".join(fl), "-map", "[musik]"] + ca + [str(tmp)])
    tmp.replace(out)
    return out


def render_clicktrack(tr, out):
    """Musik mit Metronom-Klicks auf den erkannten Schlägen (hoher Klick = Taktanfang)."""
    sr = 44100
    raw = run(ffmpeg_cmd() + ["-i", tr["path"], "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], binary=True)
    y = np.frombuffer(raw, np.float32).copy()
    y *= 0.55 / (np.percentile(np.abs(y), 99.9) + 1e-9)
    n = int(0.035 * sr)
    tt = np.arange(n) / sr
    env = np.exp(-tt / 0.008)
    hi, lo = 0.75 * np.sin(2 * np.pi * 1760 * tt) * env, 0.45 * np.sin(2 * np.pi * 1100 * tt) * env
    for b, dn in zip(tr["beats"], tr["down"]):
        k = int(round(b * sr))
        if 0 <= k < len(y) - n:
            y[k:k + n] += hi if dn else lo
    y = np.clip(y, -1, 1).astype(np.float32)
    ca, _ = audio_codec_args()
    tmp = Path(str(out) + ".tmp.ogg")
    p = subprocess.run(ffmpeg_cmd() + ["-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-"] + ca + [str(tmp)],
                       input=y.tobytes(), capture_output=True, env=clean_env())
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-300:])
    tmp.replace(out)
    return out
