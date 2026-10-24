"""Titel-Bibliothek: Vorspann und Abspann in verschiedenen Gestaltungen (Band, Karte, Linien, Leuchten …).

Die Schrift setzt ffmpeg (drawtext, beliebige installierte Schrift), alles drumherum – Flächen mit runden Ecken,
Linien, Rahmen, Schatten, Leuchten, Verläufe – entsteht hier mit numpy. Ergebnis ist ein transparentes RGBA-Bild in
Zielgröße; dasselbe Bild nutzen Live-Vorschau, Kdenlive-Projekt und Rendern.
"""
import re
import shutil
from pathlib import Path

import numpy as np

from .util import ff_path, ffmpeg_cmd, find_font, run

DUNKEL = "#1d2026"

# id → (Name de, Name en, Beschreibung de, Beschreibung en)
STILE = {
    "band": ("Band", "Band", "halbtransparentes Band über die ganze Breite", "translucent band across the width"),
    "klar": ("Klar", "Clean", "nur Schrift mit weichem Schatten", "just the text with a soft shadow"),
    "karte": ("Karte", "Card", "dunkle Fläche mit runden Ecken", "dark panel with rounded corners"),
    "hell": ("Helle Karte", "Light card", "weiße Karte, dunkle Schrift, Schatten", "white card, dark text, shadow"),
    "glas": ("Glas", "Glass", "zarte helle Fläche mit feinem Rand", "subtle light panel with a fine border"),
    "linien": ("Linien", "Lines", "feine Linien über und unter dem Titel", "fine lines above and below the title"),
    "rahmen": ("Rahmen", "Frame", "schmaler Rahmen um den Titel", "thin frame around the title"),
    "akzent": ("Bauchbinde", "Lower third", "links unten mit farbigem Akzentbalken", "bottom left with a coloured accent bar"),
    "marker": ("Marker", "Highlighter", "jede Zeile farbig hinterlegt", "each line on a coloured highlight"),
    "leuchten": ("Leuchten", "Glow", "Schrift mit farbigem Leuchten", "text with a coloured glow"),
    "kontur": ("Kontur", "Outline", "hohle Buchstaben mit Umriss", "hollow letters with an outline"),
    "verlauf": ("Kino", "Cinema", "dunkler Verlauf von unten, große Schrift", "dark gradient from below, large text"),
}
STANDARD = {"stil": "band", "schrift": "", "farbe": "#ffc23d", "position": "unten", "groesse": 100,
            "groesse_unter": 100, "fett": True, "fett_unter": False}
GROESSE = (50, 200)   # Schriftgröße in Prozent der Standardgröße

# schöne Schriften, die oft installiert sind (es werden nur vorhandene angeboten)
EMPFOHLEN = ["Noto Sans", "Inter", "Ubuntu", "Cantarell", "Open Sans", "Roboto", "Lato", "Montserrat", "Raleway",
             "Oswald", "Bebas Neue", "Fira Sans", "Source Sans 3", "Nunito", "Poppins", "Comfortaa", "Quicksand",
             "Noto Serif", "Lora", "Merriweather", "Playfair Display", "Libre Baskerville", "DejaVu Serif",
             "Liberation Serif", "Caladea", "DejaVu Sans", "Liberation Sans", "Carlito"]


def stil_liste(lang="de"):
    return [{"id": k, "name": v[1] if lang == "en" else v[0], "text": v[3] if lang == "en" else v[2]}
            for k, v in STILE.items()]


def schriften():
    """Installierte Schriftfamilien: empfohlene zuerst, dann alle weiteren."""
    fams = set()
    if shutil.which("fc-list"):
        out = run(["fc-list", "--format", "%{family[0]}\\n"], check=False)
        fams = {f.strip() for f in out.splitlines() if f.strip() and not f.startswith(".")}
    emp = [f for f in EMPFOHLEN if f in fams]
    rest = sorted(f for f in fams if f not in emp and not re.search(r"Math|Mono|Symbol|Emoji|Dingbat|Icons", f))
    return {"empfohlen": emp, "weitere": rest[:150]}


def font_file(family, bold):
    if family and shutil.which("fc-match"):
        f = run(["fc-match", "-f", "%{file}", f"{family}:{'bold' if bold else 'regular'}"], check=False).strip()
        if f and Path(f).exists():
            return f
    return find_font(bold) or find_font(True)


def _hex(c, default=(1.0, 0.76, 0.24)):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(c or ""))
    if not m:
        return np.array(default, np.float32)
    v = int(m.group(1), 16)
    return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], np.float32) / 255.0


# ───────────────────────────────────────────── kleine Bildwerkzeuge (Alpha-Masken 0…1)

def _blur(a, r):
    """Weichzeichnen: dreimal Kastenfilter ≈ Gauß."""
    r = int(max(1, r))
    for _ in range(3):
        for ax in (0, 1):
            c = np.cumsum(np.pad(a, [(r + 1, r) if i == ax else (0, 0) for i in range(2)], mode="edge"), axis=ax)
            if ax == 0:
                a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
            else:
                a = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
    return a


def _round_rect(W, H, x0, y0, x1, y1, r, feather=1.2):
    X = np.arange(W, dtype=np.float32)[None, :]
    Y = np.arange(H, dtype=np.float32)[:, None]
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    dx = np.maximum(np.maximum(x0 + r - X, X - (x1 - r)), 0)
    dy = np.maximum(np.maximum(y0 + r - Y, Y - (y1 - r)), 0)
    d = np.sqrt(dx * dx + dy * dy) - r
    return np.clip(0.5 - d / feather, 0, 1).astype(np.float32)


def _shift(a, dx, dy):
    out = np.zeros_like(a)
    H, W = a.shape
    dx, dy = int(dx), int(dy)
    out[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)] = a[max(0, -dy):H - max(0, dy), max(0, -dx):W - max(0, dx)]
    return out


class Bild:
    """RGBA-Ebene (vormultipliziert) zum Übereinanderlegen."""

    def __init__(self, W, H):
        self.rgb = np.zeros((H, W, 3), np.float32)
        self.a = np.zeros((H, W), np.float32)

    def lege(self, alpha, color):
        alpha = np.clip(alpha, 0, 1)
        self.rgb = self.rgb * (1 - alpha[..., None]) + alpha[..., None] * np.asarray(color, np.float32)
        self.a = self.a + alpha * (1 - self.a)

    def lege_rgba(self, rgb, alpha):
        self.rgb = self.rgb * (1 - alpha[..., None]) + rgb * alpha[..., None]
        self.a = self.a + alpha * (1 - self.a)

    def rgba8(self):
        rgb = self.rgb / np.maximum(self.a[..., None], 1e-6)
        out = np.concatenate([np.clip(rgb, 0, 1), self.a[..., None]], axis=2)
        return (out * 255 + 0.5).astype(np.uint8)


# ───────────────────────────────────────────── Schrift setzen

def _text_layer(lines, W, H, font_family, x_mode, y_top, color, border=0, hollow=False, tmpdir="/tmp", gap=1.32):
    """lines: [(text, px, bold)]. Gibt (rgb, alpha, Zeilen-Rechtecke) zurück."""
    filters = ["null"]
    tfiles, rows, y = [], [], y_top
    for i, (text, size, bold) in enumerate(lines):
        tf = Path(tmpdir) / f"titelzeile_{id(lines)}_{i}.txt"
        tf.write_text(text, encoding="utf-8")
        tfiles.append(tf)
        font = font_file(font_family, bold)
        fo = f"fontfile='{ff_path(font)}':" if font else ""
        x = "(w-text_w)/2" if x_mode == "mitte" else str(int(x_mode))
        fc = "white@0.0" if hollow else color
        bo = f":borderw={int(border)}:bordercolor={color}" if border else ""
        filters.append(f"drawtext={fo}textfile='{ff_path(tf)}':expansion=none:fontsize={int(size)}:fontcolor={fc}"
                       f"{bo}:x={x}:y={int(y)}")
        rows.append((int(y), int(y + size * 1.18)))
        y += int(size * (gap if i == 0 else 1.25))
    raw = run(ffmpeg_cmd() + ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H},format=rgba", "-vf",
                              ",".join(filters) + ",format=rgba", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                              "rgba", "-"], binary=True)
    for tf in tfiles:
        tf.unlink(missing_ok=True)
    img = np.frombuffer(raw, np.uint8).reshape(H, W, 4).astype(np.float32) / 255.0
    a = img[..., 3]
    boxes = []
    for r0, r1 in rows:   # tatsächliche Ausdehnung je Zeile
        band = a[max(0, r0 - 4):min(H, r1 + 8)]
        cols = np.where(band.max(axis=0) > 0.05)[0]
        rws = np.where(band.max(axis=1) > 0.05)[0]
        if len(cols) and len(rws):
            boxes.append((int(cols[0]), max(0, r0 - 4) + int(rws[0]), int(cols[-1]) + 1, max(0, r0 - 4) + int(rws[-1]) + 1))
    return img[..., :3], a, boxes


# ───────────────────────────────────────────── Titel zusammensetzen

def render(text, unter, W, H, stil=None, art="titel", tmpdir="/tmp"):
    """Titel (art="titel") oder Abspann ("abspann") als RGBA-uint8-Array (H, W, 4)."""
    st = dict(STANDARD, **(stil or {}))
    sid = st["stil"] if st["stil"] in STILE else "band"
    acc = _hex(st.get("farbe"))
    hoch = H > W
    sc = (W / 1920) if not hoch else (W / 1080)
    g = float(np.clip(float(st.get("groesse") or 100), *GROESSE)) / 100
    gu = float(np.clip(float(st.get("groesse_unter") or 100), *GROESSE)) / 100
    main = (60 if art == "abspann" else 92) * sc * (1.25 if sid == "verlauf" and art == "titel" else 1.0) * g
    sub = 46 * sc * gu
    lines = [(text, main, bool(st.get("fett", True)))] + ([(unter, sub, bool(st.get("fett_unter", False)))] if unter else [])
    block_h = main * 1.32 + (sub * 1.25 if unter else 0)
    mitte = st.get("position") == "mitte" or art == "abspann"
    cy = H * (0.5 if mitte else (0.70 if hoch else 0.75))
    if sid == "akzent" and not mitte:
        cy = H * (0.80 if not hoch else 0.74)
    y_top = cy - block_h / 2
    links = sid == "akzent"
    x_mode = int(W * (0.08 if not hoch else 0.07)) + int(28 * sc) if links else "mitte"
    dunkel_schrift = sid in ("hell", "marker")
    color = DUNKEL if dunkel_schrift else "white"
    rand = W * (0.84 if links else 0.92)       # größer als das Bild wird nichts: dann passt Pulsecut die Größe an
    for _ in range(6):
        trgb, ta, boxes = _text_layer(lines, W, H, st.get("schrift"), x_mode, y_top, color, tmpdir=tmpdir,
                                      gap=1.62 if sid == "marker" else 1.32)
        breit = max((b[2] - b[0] for b in boxes), default=0)
        if breit <= rand:
            break
        # ragt der Text übers Bild hinaus, ist er abgeschnitten und eigentlich noch breiter: dann kräftiger verkleinern
        f = rand / breit * 0.98 if max(b[2] for b in boxes) < W - 2 and min(b[0] for b in boxes) > 1 else 0.7
        lines = [(t, z * f, b) for t, z, b in lines]
        block_h *= f
        y_top = cy - block_h / 2
    if not boxes:
        return Bild(W, H).rgba8()
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    px, py = 46 * sc, 26 * sc
    out = Bild(W, H)
    black, white = np.zeros(3, np.float32), np.ones(3, np.float32)

    def schatten(alpha, r=10, dx=4, dy=5, stark=0.55):
        out.lege(_shift(_blur(alpha, r * sc), dx * sc, dy * sc) * stark, black)

    if sid == "band":
        ys = np.arange(H, dtype=np.float32)
        b0, b1 = y0 - py * 1.3, y1 + py * 1.3
        band = np.clip(np.minimum(ys - b0, b1 - ys) / (40.0 * sc) + 0.5, 0, 1) * 0.45
        out.lege(np.broadcast_to(band[:, None], (H, W)).copy(), black)
        schatten(ta, 3, 3, 3, 0.7)
    elif sid == "klar":
        schatten(ta, 12, 0, 4, 0.75)
        schatten(ta, 3, 2, 2, 0.5)
    elif sid == "karte":
        card = _round_rect(W, H, x0 - px, y0 - py, x1 + px, y1 + py, 18 * sc)
        out.lege(card * 0.62, black)
    elif sid == "hell":
        card = _round_rect(W, H, x0 - px, y0 - py, x1 + px, y1 + py, 16 * sc)
        schatten(card, 18, 0, 8, 0.45)
        out.lege(card * 0.94, white)
    elif sid == "glas":
        card = _round_rect(W, H, x0 - px, y0 - py, x1 + px, y1 + py, 22 * sc)
        inner = _round_rect(W, H, x0 - px + 2 * sc, y0 - py + 2 * sc, x1 + px - 2 * sc, y1 + py - 2 * sc, 20 * sc)
        out.lege(card * 0.22, black)
        out.lege(card * 0.16, white)
        out.lege(np.clip(card - inner, 0, 1) * 0.75, white)
        schatten(ta, 6, 2, 3, 0.45)
    elif sid == "linien":
        w2 = (x1 - x0) / 2 + 70 * sc
        cx = (x0 + x1) / 2
        t = max(2.0, 4 * sc)
        for yy in (y0 - py - t, y1 + py):
            line = _round_rect(W, H, cx - w2, yy, cx + w2, yy + t, t / 2)
            out.lege(line * 0.95, acc)
        schatten(ta, 8, 0, 3, 0.6)
    elif sid == "rahmen":
        t = max(2.0, 4 * sc)
        outer = _round_rect(W, H, x0 - px, y0 - py, x1 + px, y1 + py, 2 * sc)
        inner = _round_rect(W, H, x0 - px + t, y0 - py + t, x1 + px - t, y1 + py - t, 1)
        out.lege(outer * 0.25, black)
        out.lege(np.clip(outer - inner, 0, 1), white)
        schatten(ta, 6, 2, 3, 0.5)
    elif sid == "akzent":
        bx0 = W * (0.08 if not hoch else 0.07)
        box = _round_rect(W, H, bx0, y0 - py, x1 + px, y1 + py, 4 * sc)
        out.lege(box * 0.62, black)
        bar = _round_rect(W, H, bx0, y0 - py, bx0 + 10 * sc, y1 + py, 2 * sc)
        out.lege(bar, acc)
    elif sid == "marker":
        for i, (bx0, by0, bx1, by1) in enumerate(boxes):
            pad = (22 if i == 0 else 14) * sc
            m = _round_rect(W, H, bx0 - pad, by0 - pad * 0.55, bx1 + pad, by1 + pad * 0.55, 6 * sc)
            schatten(m, 10, 0, 5, 0.35)
            out.lege(m, acc if i == 0 else white)
    elif sid == "leuchten":
        glow = _blur(ta, 16 * sc)
        out.lege(np.clip(glow * 2.2, 0, 1) * 0.9, acc)
        out.lege(np.clip(_blur(ta, 5 * sc) * 1.6, 0, 1) * 0.8, acc)
    elif sid == "kontur":   # hohle Buchstaben: nur ein Ring um die Schrift
        grow = np.clip(_blur(ta, max(1.0, 2.2 * sc)) * 3.2, 0, 1)
        ring = np.clip(grow - ta * 1.15, 0, 1)
        schatten(grow, 8, 0, 3, 0.5)
        out.lege(ring, white)
        return out.rgba8()
    elif sid == "verlauf":
        ys = np.arange(H, dtype=np.float32)
        start = y0 - (y1 - y0) * 1.4
        g = np.clip((ys - start) / max(1.0, H - start), 0, 1) ** 1.4 * 0.78
        out.lege(np.broadcast_to(g[:, None], (H, W)).copy(), black)
        schatten(ta, 10, 0, 4, 0.6)
    out.lege_rgba(trgb, ta)
    return out.rgba8()


def vorschau_auf(bild_rgb, rgba):
    """Titel über ein Bild legen (für die Auswahl-Galerie)."""
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    out = bild_rgb.astype(np.float32) * (1 - a) + rgba[..., :3].astype(np.float32) * a
    return np.concatenate([out, np.full(a.shape, 255.0)], axis=2).astype(np.uint8)

