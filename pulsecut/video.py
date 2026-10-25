"""Videos: Erfassen (Zeit, Format), Analyse (Qualität, Perspektiven, Kamerabewegung, Ton), Vorschau-Proxys."""
import json
import math
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import hwdec as HW
from .i18n import L as _t
from .util import (ddist, ffmpeg_cmd, md5, parse_iso, r, run, smoothstep)

ANALYSE_VERSION = 6
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".mts", ".m2ts", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv"}
VIEW_THR = 0.42        # ab diesem Bildabstand gilt eine Einstellung als neue Perspektive
ADJ_THR = 0.38         # Mindestabstand zwischen zwei aufeinanderfolgenden Schnitten

FILENAME_PATTERNS = [
    re.compile(r"(20\d\d)(\d\d)(\d\d)[_\-\s]?(\d\d)(\d\d)(\d\d)"),
    re.compile(r"(20\d\d)-(\d\d)-(\d\d)[ _]at[ _](\d\d)\.(\d\d)\.(\d\d)"),
    re.compile(r"(20\d\d)-(\d\d)-(\d\d)[ _T-](\d\d)[\.\-:](\d\d)[\.\-:](\d\d)"),
]

def zeit_aus_name(name):
    """Aufnahmezeit aus dem Dateinamen (VID_20260713_091000.mp4, PXL_…, „2026-07-14 at 21.15.00“) oder None."""
    for pat in FILENAME_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                return datetime(*map(int, m.groups()))
            except ValueError:
                pass
    return None


BEWEGUNG_LABEL = {"rechts": "Schwenk nach rechts", "links": "Schwenk nach links", "hoch": "Neigung nach oben",
                  "runter": "Neigung nach unten", "rein": "Zoom rein / ran", "raus": "Zoom raus / weg",
                  "ruhig": "ruhig"}


class Clip:
    def __init__(self, path, idx):
        self.idx = idx
        self.path = Path(path).resolve()
        self.name = self.path.name
        st = self.path.stat()
        self.size = st.st_size
        self.mtime = st.st_mtime
        self.key = f"{self.path}|{self.size}|{int(self.mtime)}"
        self.hash = md5(self.key)[:12]
        self.dur = 0.0
        self.w = self.h = 0
        self.fps = 30.0
        self.has_audio = False
        self.codec = None       # Videocodec, Pixelformat und Drehung (für die Hardware-Dekodierung)
        self.pix = None
        self.rot = 0
        self.start = None
        self.time_source = ""
        self.name_start = zeit_aus_name(self.name)   # zum Gegenprüfen der Aufnahmetage
        self.ana = None
        self.q = None
        self.times = None
        self.cuts = None
        self.mean_q = 0.0
        self.good_sec = 0.0
        self.segs = []
        self.desc = None
        self.dtimes = []
        self.order = idx
        # vom Benutzer
        self.prio = ""          # "" / "hoch" / "raus"
        self.ton = ""           # Originalton: "" automatisch / "an" bevorzugt / "aus" nie
        self.kat_manuell = ""   # Stichwort-ID
        self.excl = []          # abgewählte Passagen

    @property
    def aspect(self):
        return self.w / self.h if self.h else 16 / 9

    @property
    def portrait(self):
        return self.aspect < 0.95

    def needs_bg(self, out_aspect=16 / 9):
        return abs(self.aspect - out_aspect) > 0.06

    @property
    def end(self):
        return self.start + timedelta(seconds=self.dur)

    def probe(self):
        data = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                               "-show_format", "-show_streams", str(self.path)]))
        vs = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"):
                vs = vs or s
            if s.get("codec_type") == "audio":
                self.has_audio = True
        if vs is None:
            raise RuntimeError(_t("keine Videospur"))
        w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
        rot = 0
        for sd in vs.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        if not rot and "rotate" in (vs.get("tags") or {}):
            rot = int(float(vs["tags"]["rotate"]))
        sar = vs.get("sample_aspect_ratio", "1:1")
        try:
            a, b = (int(x) for x in sar.split(":"))
            if a > 0 and b > 0 and a != b:
                w = int(round(w * a / b))
        except ValueError:
            pass
        if abs(rot) % 180 == 90:
            w, h = h, w
        self.w, self.h = w, h
        self.codec, self.pix, self.rot = vs.get("codec_name") or "", vs.get("pix_fmt") or "", rot
        try:
            num, den = vs.get("avg_frame_rate", "30/1").split("/")
            self.fps = float(num) / float(den) if float(den) else 30.0
        except (ValueError, ZeroDivisionError):
            self.fps = 30.0
        self.dur = float(data.get("format", {}).get("duration") or vs.get("duration") or 0)
        fmt_tags = {k.lower(): v for k, v in (data.get("format", {}).get("tags") or {}).items()}
        st_tags = {k.lower(): v for k, v in (vs.get("tags") or {}).items()}
        for src, val in (("Handy-Metadaten", fmt_tags.get("com.apple.quicktime.creationdate")),
                         ("Metadaten", fmt_tags.get("creation_time")), ("Metadaten", st_tags.get("creation_time"))):
            dt = parse_iso(val)
            if dt:
                self.start, self.time_source = dt, src
                break
        if self.start is None:
            for pat in FILENAME_PATTERNS:
                m = pat.search(self.name)
                if m:
                    try:
                        self.start = datetime(*map(int, m.groups()))
                        self.time_source = "Dateiname"
                        break
                    except ValueError:
                        pass
        if self.start is None:
            self.start = datetime.fromtimestamp(self.mtime)
            self.time_source = "Dateidatum"

    def to_meta(self):
        return {"w": self.w, "h": self.h, "fps": self.fps, "dur": self.dur, "audio": self.has_audio,
                "start": self.start.isoformat(), "quelle": self.time_source,
                "codec": self.codec, "pix": self.pix, "rot": self.rot}

    def from_meta(self, m):
        self.w, self.h, self.fps, self.dur = m["w"], m["h"], m["fps"], m["dur"]
        self.has_audio = m["audio"]
        self.start = datetime.fromisoformat(m["start"])
        self.time_source = m["quelle"]
        self.codec, self.pix, self.rot = m.get("codec"), m.get("pix"), m.get("rot", 0)


# ═════════════════════════════════════════════ Bild- und Tonanalyse

def phase_corr(a, b, win):
    fa = np.fft.rfft2(a * win)
    fb = np.fft.rfft2(b * win)
    rr = fa * np.conj(fb)
    rr /= np.abs(rr) + 1e-6
    c = np.fft.irfft2(rr, s=a.shape)
    idx = int(np.argmax(c))
    dy, dx = divmod(idx, a.shape[1])
    if dy > a.shape[0] // 2:
        dy -= a.shape[0]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    return dy, dx


def area_resize(img, H, W):
    h, w = img.shape[:2]
    ys = (np.arange(H + 1) * h / H).astype(int)
    xs = (np.arange(W + 1) * w / W).astype(int)
    cy = np.maximum(1, np.diff(ys)).reshape((-1,) + (1,) * (img.ndim - 1))
    rows = np.add.reduceat(img, ys[:-1], axis=0) / cy
    cx = np.maximum(1, np.diff(xs)).reshape((1, -1) + (1,) * (img.ndim - 2))
    return np.add.reduceat(rows, xs[:-1], axis=1) / cx


def view_descriptor(rgb):
    """Perspektiv-Deskriptor: grobe Helligkeits-, Farb- und Kantenverteilung (16×9 Felder)."""
    f = rgb.astype(np.float32)
    sm = area_resize(f, 36, 64)
    R, G, B = sm[..., 0], sm[..., 1], sm[..., 2]
    L = (R + G + B) / 3
    a = R - G
    b = (R + G) / 2 - B
    E = np.zeros_like(L)
    E[:-1, :-1] = np.abs(np.diff(L, axis=1))[:-1, :] + np.abs(np.diff(L, axis=0))[:, :-1]
    Lp, ap, bp, Ep = (area_resize(x, 9, 16) for x in (L, a, b, E))

    def z(x):
        return (x - x.mean()) / (x.std() + 8)

    return np.concatenate([z(Lp).ravel(), (ap / 40).ravel() * 0.6, (bp / 40).ravel() * 0.6,
                           z(Ep).ravel() * 0.8]).astype(np.float16)


def phase_corr_sub(a, b, win):
    """Verschiebung von b gegenüber a (Unterpixel genau, Phasenkorrelation)."""
    fa = np.fft.rfft2(a * win)
    fb = np.fft.rfft2(b * win)
    rr = fb * np.conj(fa)
    rr /= np.abs(rr) + 1e-6
    c = np.fft.irfft2(rr, s=a.shape)
    h, w = a.shape
    iy, ix = divmod(int(np.argmax(c)), w)

    def sub(cm, c0, cp):
        den = cm - 2 * c0 + cp
        return 0.0 if den >= 0 else float(np.clip(0.5 * (cm - cp) / den, -0.5, 0.5))

    dy = iy + sub(c[(iy - 1) % h, ix], c[iy, ix], c[(iy + 1) % h, ix])
    dx = ix + sub(c[iy, (ix - 1) % w], c[iy, ix], c[iy, (ix + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return dy, dx


def _sample(img, ys, xs):
    """Bilineare Abtastung von img an (ys, xs)."""
    h, w = img.shape
    ys = np.clip(ys, 0, h - 1.001)
    xs = np.clip(xs, 0, w - 1.001)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = ys - y0, xs - x0
    a = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    b = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


_MWIN = {}


def motion_between(g0, g1, dt):
    """Kamerabewegung zwischen zwei Graubildern: Schwenk x/y (Bildbreiten pro s) und Zoom (Maßstab pro s).
    Schwenk per Phasenkorrelation, Zoom durch Vergleich mit leicht vergrößerten/verkleinerten Fassungen."""
    g0 = g0.astype(np.float32)
    g1 = g1.astype(np.float32)
    h, w = g0.shape
    key = (h, w)
    if key not in _MWIN:
        _MWIN[key] = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        m = (yy > h * 0.15) & (yy < h * 0.85) & (xx > w * 0.15) & (xx < w * 0.85)
        _MWIN[key] = (_MWIN[key], yy[m], xx[m], m)
    win, ys, xs, m = _MWIN[key]
    dy, dx = phase_corr_sub(g0, g1, win)
    cy, cx = (h - 1) / 2, (w - 1) / 2
    target = g1[m]
    errs = []
    scales = (0.955, 0.97, 0.985, 1.0, 1.015, 1.03, 1.045)
    for sc in scales:   # g1(p) ≈ g0(c + (p - c)/sc - d)
        smp = _sample(g0, cy + (ys - cy) / sc - dy, cx + (xs - cx) / sc - dx)
        errs.append(float(np.mean(np.abs(smp - target))))
    j = int(np.argmin(errs))
    sc = scales[j]
    if 0 < j < len(scales) - 1:
        e0, e1, e2 = errs[j - 1], errs[j], errs[j + 1]
        den = e0 - 2 * e1 + e2
        if den > 1e-9:
            sc += float(np.clip(0.5 * (e0 - e2) / den, -0.5, 0.5)) * 0.015
    # Kamera schwenkt nach rechts → Bildinhalt wandert nach links (dx < 0)
    return -dx / w / dt, -dy / w / dt, (sc - 1.0) / dt


def analyse_audio_dsp(path):
    """Ton-Merkmale je 0,5 s aus einer Datei (eigener Durchgang)."""
    raw = run(ffmpeg_cmd() + ["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
              binary=True, check=False)
    return analyse_audio(np.frombuffer(raw, np.float32))


def analyse_audio(y):
    """Ton-Merkmale je 0,5 s: Lautstärke, Musik-Wahrscheinlichkeit (gehaltene Töne), Rauschanteil.
    y = Mono-Ton mit 16 kHz."""
    sr, n_fft, hop = 16000, 1024, 512
    if len(y) < sr:
        return None
    nfr = 1 + (len(y) - n_fft) // hop
    win = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = (freqs >= 150) & (freqs <= 6000)
    pkb = (freqs >= 100) & (freqs <= 4000)
    pw = np.zeros(nfr, np.float64)
    flat = np.zeros(nfr, np.float32)
    peaks = np.zeros((nfr, int(pkb.sum()) - 2), bool)
    k = 13
    for s0 in range(0, nfr, 1024):
        idx = np.arange(s0, min(nfr, s0 + 1024))
        fr0 = y[idx[:, None] * hop + np.arange(n_fft)[None, :]]
        pw[idx] = (fr0.astype(np.float64) ** 2).mean(axis=1)
        P = np.abs(np.fft.rfft(fr0 * win, axis=1)) ** 2 + 1e-10
        Pb = P[:, band]
        flat[idx] = np.exp(np.log(Pb).mean(axis=1)) / Pb.mean(axis=1)
        Lg = 10 * np.log10(P[:, pkb])
        cs = np.cumsum(np.pad(Lg, ((0, 0), (k // 2 + 1, k // 2)), mode="edge"), axis=1)
        ma = (cs[:, k:] - cs[:, :-k]) / k
        mid = Lg[:, 1:-1]
        locmax = (mid > Lg[:, :-2]) & (mid >= Lg[:, 2:])
        prom = mid - ma[:, 1:-1] > 8
        loud = mid > (Lg.max(axis=1, keepdims=True) - 45)
        peaks[idx] = locmax & prom & loud
    pkd = peaks.copy()
    pkd[:, 1:] |= peaks[:, :-1]
    pkd[:, :-1] |= peaks[:, 1:]
    lag1, lag2 = 3, 6
    pers = np.zeros(nfr, np.float32)
    cnt = peaks.sum(axis=1)
    if nfr > lag2:
        keep = peaks[:-lag2] & pkd[lag1:nfr - lag2 + lag1] & pkd[lag2:]
        pers[:-lag2] = keep.sum(axis=1) / np.maximum(1, cnt[:-lag2])
    t_fr = (np.arange(nfr) * hop + n_fft / 2) / sr
    nb = int(math.ceil(t_fr[-1] / 0.5)) + 1
    bi = np.minimum(nb - 1, (t_fr / 0.5).astype(int))
    fdb = 10 * np.log10(pw + 1e-10)
    db, fl, pe, mod = np.full(nb, -90.0), np.zeros(nb), np.zeros(nb), np.zeros(nb)
    for b in range(nb):
        m = bi == b
        if not m.any():
            continue
        db[b] = 10 * math.log10(pw[m].mean() + 1e-12)
        fl[b] = float(np.median(flat[m]))
        mm = m & (cnt >= 2)
        pe[b] = float(pers[mm].mean()) if mm.any() else 0.0
        mod[b] = float(np.std(np.maximum(fdb[m], db[b] - 30)))
    music = np.clip((pe - 0.30) / 0.30, 0, 1) * np.clip((0.30 - fl) / 0.20, 0, 1)
    music = np.convolve(np.pad(music, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    music[db < -55] = 0
    noise = np.clip((fl - 0.12) / 0.25, 0, 1) * np.clip((mod - 2.5) / 4.0, 0, 1) * (1 - music)
    return {"t": r((np.arange(nb) + 0.5) * 0.5, 2), "db": r(db, 1), "musik": r(music, 3), "rauschen": r(noise, 3)}


KF_ONLY_AB = 240.0      # längere Videos: für die Analyse nur Schlüsselbilder


def keyframes_only(clip):
    return clip.dur > KF_ONLY_AB


def _proxy_args(clip, tmp):
    """Ausgabe-Optionen der Vorschau-Videos (VP8 + Opus, Schlüsselbild alle 0,4 s)."""
    g = max(6, int(round(clip.fps * 0.4)))
    a = ["-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "800k",
         "-crf", "28", "-qmin", "4", "-qmax", "48", "-g", str(g), "-auto-alt-ref", "0"]
    a += (["-map", "0:a:0?", "-c:a", "libopus", "-b:a", "64k", "-ac", "2"] if clip.has_audio else [])
    return a + [str(tmp)]


def _proxy_chain(clip, hw):
    if hw:
        pw, ph = HW.proxy_size(clip)
        return f"{HW.verkleinern(pw, ph, clip.rot)},setsar=1,format=yuv420p"
    sc = "scale=-2:360" if clip.w >= clip.h else "scale=360:-2"
    return f"{sc}:flags=bilinear,format=yuv420p"


def analyse_clip(clip, dirs, proxy=None, hw=False):
    """Bildmerkmale (4/s), Bewegung, Perspektiv-Deskriptoren (2/s), Bilder für KI und Vorschau, Ton.
    In einem einzigen ffmpeg-Durchgang: mit proxy (Pfad) entsteht im selben Lauf das Vorschau-Video, der Ton wird
    ebenfalls mitgelesen. hw = über den Grafikchip dekodieren (siehe hwdec.py; das Ergebnis ist dasselbe)."""
    if clip.w >= clip.h:
        aw, ah = 256, max(2, int(round(256 * clip.h / clip.w / 2)) * 2)
        kh, kw = 256, max(2, int(round(256 * clip.w / clip.h / 2)) * 2)
    else:
        ah, aw = 256, max(2, int(round(256 * clip.w / clip.h / 2)) * 2)
        kw, kh = 256, max(2, int(round(256 * clip.h / clip.w / 2)) * 2)
    kf_only = keyframes_only(clip)
    if kf_only:
        proxy = None
    ki_every = 1.0 if clip.dur <= 120 else 2.0
    fdir = dirs["bilder"] / clip.hash
    if fdir.exists():
        shutil.rmtree(fdir)
    fdir.mkdir(parents=True)
    graph, vin = [], "[0:v]"
    if proxy:
        graph.append("[0:v]split=2[pin][xin]")
        graph.append(f"[pin]{_proxy_chain(clip, hw)}[pv]")
        vin = "[xin]"
    pre = "" if kf_only else "fps=4"
    if hw:
        pre = ",".join(x for x in (pre, HW.herunterladen(clip.rot, clip.pix)) if x)
    graph.append(f"{vin}{pre + ',' if pre else ''}split=2[a][b]")
    graph.append(f"[a]scale={aw}:{ah}:flags=area,format=rgb24[a1]")
    graph.append(f"[b]fps=1/{ki_every},scale={kw}:{kh}:flags=bicubic[b1]")
    cmd = ffmpeg_cmd() + HW.eingang(hw)
    if kf_only:
        cmd += ["-skip_frame:v", "nokey"]
    cmd += ["-i", str(clip.path), "-filter_complex", ";".join(graph),
            "-map", "[a1]"] + (["-fps_mode", "passthrough"] if kf_only else []) + \
           ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1", "-map", "[b1]", "-q:v", "4", str(fdir / "f_%04d.jpg")]
    ptmp = Path(str(proxy) + ".tmp.webm") if proxy else None
    if proxy:
        cmd += ["-map", "[pv]"] + _proxy_args(clip, ptmp)
    tonf = fdir / "ton.f32"
    if clip.has_audio:
        cmd += ["-map", "0:a:0?", "-ac", "1", "-ar", "16000", "-f", "f32le", str(tonf)]
    try:
        raw = run(cmd, binary=True)
    except Exception:
        for f in (ptmp, tonf):
            if f is not None and f.exists():
                f.unlink()
        raise
    fsz = aw * ah * 3
    n = len(raw) // fsz
    if n == 0:
        raise RuntimeError(_t("keine Bilder dekodiert"))
    frames = np.frombuffer(raw[:n * fsz], np.uint8).reshape(n, ah, aw, 3)
    times = (np.arange(n) + 0.5) * clip.dur / n if kf_only else np.arange(n) / 4.0
    gh, gw = ah // 2, aw // 2
    small_win = np.outer(np.hanning(gh), np.hanning(gw)).astype(np.float32)
    bright, contrast, sharp, cam, resid, hdiff, dxs, dys = [], [], [], [], [], [], [], []
    mx, my, mz = [], [], []
    descs, dtimes = [], []
    prev = prev_s = prev_h = prev_g = None
    last_dt = -10.0
    for i in range(n):
        rgb = frames[i]
        f = (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)
        bright.append(float(f.mean()))
        sd = float(f.std())
        contrast.append(sd)
        lap = 4 * f[1:-1, 1:-1] - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:]
        sharp.append(float(np.abs(lap).mean() / (sd + 4.0)))
        s = f[:gh * 2:2, :gw * 2:2]
        g8 = np.ascontiguousarray(s.astype(np.uint8))
        hist = np.bincount((f.astype(np.uint8) >> 4).ravel(), minlength=16).astype(np.float32) / f.size
        if prev is None:
            for lst in (cam, resid, hdiff, dxs, dys, mx, my, mz):
                lst.append(0.0)
        else:
            dt = max(1e-3, times[i] - times[i - 1])
            dy, dx = phase_corr(prev_s, s, small_win)
            dxs.append(dx / s.shape[1])
            dys.append(dy / s.shape[0])
            cam.append(float(math.hypot(dx / s.shape[1], dy / s.shape[0]) / dt))
            sh = np.roll(np.roll(prev, 2 * dy, axis=0), 2 * dx, axis=1)
            yy, xx = min(ah // 3, abs(2 * dy) + 2), min(aw // 3, abs(2 * dx) + 2)
            dd = np.abs(f[yy:ah - yy, xx:aw - xx] - sh[yy:ah - yy, xx:aw - xx])
            resid.append(float(dd.mean() / 255.0 / max(dt, 0.25) * 0.25))
            hdiff.append(float(np.abs(hist - prev_h).sum()))
            if kf_only:
                a1 = a2 = a3 = 0.0
            else:
                a1, a2, a3 = motion_between(prev_g, g8, dt)
            mx.append(a1)
            my.append(a2)
            mz.append(a3)
        if times[i] - last_dt >= 0.49 or kf_only:
            descs.append(view_descriptor(rgb))
            dtimes.append(float(times[i]))
            last_dt = times[i]
        prev, prev_s, prev_h, prev_g = f, s, hist, g8
    np.save(dirs["deskriptoren"] / f"{clip.hash}.npy", np.stack(descs))
    kfiles = sorted(p.name for p in fdir.glob("f_*.jpg"))
    ki_frames = [[round(min(clip.dur - 0.05, (j + 0.5) * ki_every), 2), nm] for j, nm in enumerate(kfiles)]
    ton = None
    if clip.has_audio and tonf.exists():
        ton = analyse_audio(np.fromfile(tonf, np.float32))
        tonf.unlink()
    if proxy:
        ptmp.replace(proxy)
    return {"v": ANALYSE_VERSION, "times": r(times, 3), "bright": r(bright, 1), "contrast": r(contrast, 1),
            "sharp": r(sharp), "cam": r(cam), "resid": r(resid, 5), "hdiff": r(hdiff, 3), "dx": r(dxs), "dy": r(dys),
            "mx": r(mx), "my": r(my), "mz": r(mz), "dtimes": r(dtimes, 2), "ki_frames": ki_frames,
            "keyframes_only": kf_only, "ton": ton}


def make_proxy(clip, out, hw=False):
    """Kleine WebM-Fassung für die Live-Vorschau im Programm (eigener Durchgang, wenn die Analyse schon da ist)."""
    tmp = Path(str(out) + ".tmp.webm")
    cmd = ffmpeg_cmd() + HW.eingang(hw) + ["-y", "-i", str(clip.path), "-filter_complex",
                                           f"[0:v]{_proxy_chain(clip, hw)}[pv]", "-map", "[pv]"]
    try:
        run(cmd + _proxy_args(clip, tmp))
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    tmp.replace(out)


# ═════════════════════════════════════════════ Qualität, Perspektiven, Bewegung

def compute_quality(clips):
    clips = [c for c in clips if c.ana]
    if not clips:
        return
    allsharp = np.concatenate([np.array(c.ana["sharp"]) for c in clips])
    allbright = np.concatenate([np.array(c.ana["bright"]) for c in clips])
    allres = np.concatenate([np.array(c.ana["resid"]) for c in clips])
    ok = allbright > 35
    ref = allsharp[ok] if ok.sum() > 20 else allsharp
    p15, p65 = np.percentile(ref, 15), np.percentile(ref, 65)
    span = max(p65 - p15, 0.15 * p65, 1e-6)
    lo = p65 - 1.6 * span
    r60 = max(np.percentile(allres, 60), 1e-4)
    for c in clips:
        a = c.ana
        t = np.array(a["times"])
        sharp = np.clip((np.array(a["sharp"]) - lo) / (p65 - lo), 0, 1) ** 0.8
        b = np.array(a["bright"])
        expo = smoothstep(b, 18, 48) * (1 - 0.6 * smoothstep(b, 220, 250))
        expo = expo * (0.55 + 0.45 * smoothstep(np.array(a["contrast"]), 6, 16))
        cam = np.array(a["cam"])
        stab = 1 - smoothstep(cam, 0.35, 1.2)
        if not a.get("keyframes_only") and len(cam) > 3:
            d = np.stack([np.array(a["dx"]), np.array(a["dy"])], axis=1)
            jit = np.r_[0.0, np.linalg.norm(np.diff(d, axis=0), axis=1)]
            jit = np.convolve(np.pad(jit, 2, mode="edge"), np.ones(5) / 5, mode="valid")
            stab = stab * (1 - 0.75 * smoothstep(jit, 0.025, 0.08))
        act = 0.7 + 0.3 * np.clip(np.array(a["resid"]) / r60, 0, 1)
        q = sharp * expo * stab * act
        if len(q) >= 3:
            q = np.convolve(np.pad(q, 1, mode="edge"), np.ones(3) / 3, mode="valid")
        q[(t < 0.4) | (t > c.dur - 0.4)] *= 0.3
        c.times, c.q = t, q
        c.cuts = (np.array(a["hdiff"]) > 0.55) | (cam > 1.4)
        c.mean_q = float(q[q > 0].mean()) if (q > 0).any() else 0.0
    med = float(np.median([c.mean_q for c in clips])) if clips else 0.5
    thr = min(0.35, max(0.08, 0.6 * med))
    for c in clips:
        dt = (c.dur / len(c.times)) if len(c.times) else 0.25
        c.good_sec = float((c.q >= thr).sum() * dt)
        c.q_thr = thr


def segment_views(c):
    """Teilt einen Clip in Perspektiven (Sichten)."""
    D = c.desc.astype(np.float32)
    T = np.asarray(c.dtimes)
    n = len(D)
    if n == 0:
        c.segs = []
        return
    cut_t = c.times[c.cuts] if c.cuts is not None and len(c.times) else np.array([])
    bounds = [0]
    anchor = D[0]
    for i in range(1, n):
        hard = bool(len(cut_t)) and bool(((cut_t > T[i - 1]) & (cut_t <= T[i])).any())
        if ddist(D[i], anchor) > VIEW_THR or hard:
            bounds.append(i)
            anchor = D[i]
    bounds.append(n)
    segs = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        t0 = 0.0 if a == 0 else float((T[a - 1] + T[a]) / 2)
        t1 = c.dur if b == n else float((T[b - 1] + T[b]) / 2)
        segs.append({"t0": t0, "t1": t1, "desc": D[a:b].mean(axis=0), "i0": a, "i1": b})
    merged = []
    for s in segs:
        if merged and s["t1"] - s["t0"] < 1.0:
            merged[-1]["t1"] = s["t1"]
            merged[-1]["i1"] = s["i1"]
        else:
            merged.append(s)
    if len(merged) > 1 and merged[0]["t1"] - merged[0]["t0"] < 1.0:
        merged[1]["t0"] = merged[0]["t0"]
        merged[1]["i0"] = merged[0]["i0"]
        merged.pop(0)
    c.segs = merged


def seg_at(c, t):
    for i, s in enumerate(c.segs):
        if s["t0"] <= t < s["t1"]:
            return i
    return len(c.segs) - 1


def desc_at(c, t):
    T = np.asarray(c.dtimes)
    i = int(np.clip(np.searchsorted(T, t), 0, len(T) - 1))
    if i > 0 and abs(T[i - 1] - t) < abs(T[i] - t):
        i -= 1
    return c.desc[i].astype(np.float32)


def prepare_clip_arrays(c):
    """Vorberechnete Raster (0,25 s) für schnelle Fensterbewertung."""
    grid = np.arange(0.0, max(0.25, c.dur), 0.25)
    q = np.interp(grid, c.times, c.q) if len(c.times) > 1 else np.full(len(grid), float(c.q[0]) if len(c.q) else 0.5)
    c.grid, c.qg = grid, q
    c.cq = np.r_[0.0, np.cumsum(q)]
    cutpos = c.times[c.cuts] if len(c.times) else np.array([])
    c.cutpos = cutpos
    a = c.ana
    if a.get("mx") and len(a["mx"]) == len(c.times) and len(c.times) > 1:
        c.mv = np.stack([np.interp(grid, c.times, np.array(a[k])) for k in ("mx", "my", "mz")], axis=1)
    else:
        c.mv = np.zeros((len(grid), 3))
    c.cmv = np.vstack([np.zeros((1, 3)), np.cumsum(c.mv, axis=0)])


def window_score(c, st, L):
    """Qualität eines Ausschnitts (Mittel/Minimum), Abzug für harte Schnitte im Clip."""
    i0 = int(max(0, st) / 0.25)
    i1 = max(i0 + 1, int(min(c.dur, st + L) / 0.25))
    i1 = min(i1, len(c.qg))
    if i1 <= i0:
        return 0.0
    mean = (c.cq[i1] - c.cq[i0]) / (i1 - i0)
    mn = float(c.qg[i0:i1].min())
    sc = 0.7 * mean + 0.3 * mn
    if len(c.cutpos) and ((c.cutpos > st + 0.2) & (c.cutpos < st + L - 0.2)).any():
        sc -= 1.0
    return float(sc)


def window_motion(c, st, L):
    i0 = int(max(0, st) / 0.25)
    i1 = min(len(c.mv), max(i0 + 1, int(min(c.dur, st + L) / 0.25)))
    if i1 <= i0:
        return np.zeros(3)
    return (c.cmv[i1] - c.cmv[i0]) / (i1 - i0)


def motion_label(v):
    mx, my, mz = float(v[0]), float(v[1]), float(v[2])
    cand = [(abs(mx), "rechts" if mx > 0 else "links", 0.035), (abs(my), "runter" if my > 0 else "hoch", 0.035),
            (abs(mz) * 1.6, "rein" if mz > 0 else "raus", 0.035)]
    mag, lab, thr = max(cand, key=lambda x: x[0])
    return lab if mag >= thr else "ruhig"


def motion_vec(v):
    return np.array([float(v[0]), float(v[1]), float(v[2]) * 1.6])


def motion_contrast(va, vb):
    """0 = gleiche Bewegung, 1 = gegenläufig; Wechsel der Bewegungsart (Schwenk ↔ Zoom) ≈ 0,6."""
    a, b = motion_vec(va), motion_vec(vb)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    still_a, still_b = na < 0.035, nb < 0.035
    if still_a and still_b:
        return 0.35
    if still_a or still_b:
        return 0.55
    cos = float(np.dot(a, b) / (na * nb))
    return float(np.clip(0.5 - 0.5 * cos + (0.1 if abs(cos) < 0.4 else 0.0), 0, 1))
