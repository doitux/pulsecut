"""Title library: every style renders, fonts can be chosen, export and preview use the same picture."""
import numpy as np
import pytest

from conftest import prepare
from pulsecut import titel as TI


@pytest.mark.parametrize("sid", list(TI.STILE))
def test_every_style_renders(sid, tmp_path):
    img = TI.render("Sommerfreizeit 2026", "Ein Sommer voller Musik", 640, 360, {"stil": sid}, "titel", tmp_path)
    assert img.shape == (360, 640, 4) and img.dtype == np.uint8
    a = img[..., 3]
    assert a.max() == 255 and (a > 0).mean() < 0.6
    rows = np.where(a.max(axis=1) > 0)[0]
    assert rows[-1] > 150            # title sits in the lower part or the middle
    portrait = TI.render("Titel", "", 360, 640, {"stil": sid}, "abspann", tmp_path)
    assert portrait.shape == (640, 360, 4) and portrait[..., 3].max() > 0


def test_fonts_listed_and_used(tmp_path):
    f = TI.schriften()
    assert isinstance(f["empfohlen"], list) and isinstance(f["weitere"], list)
    fams = f["empfohlen"] + f["weitere"]
    if len(fams) >= 2:
        a = TI.render("Abc Titel", "", 640, 360, {"stil": "klar", "schrift": fams[0]}, "titel", tmp_path)
        b = TI.render("Abc Titel", "", 640, 360, {"stil": "klar", "schrift": fams[-1]}, "titel", tmp_path)
        assert a.shape == b.shape


def test_style_in_export_and_preview(projekt, tmp_path):
    from pulsecut import export as EX
    prepare(projekt, titelstil={"stil": "karte", "schrift": "", "farbe": "#22aaee", "position": "mitte"})
    projekt.d["schnitt"].update({"titel": "Camp 2026", "untertitel": "Test", "abspann": "Danke!"})
    info = projekt.timeline_info()
    assert [t["art"] for t in info["titel"]] == ["titel", "abspann"] and info["titel"][0]["bild"].startswith("/media/titel/0.png")
    pv = projekt.titel_vorschau(0)
    assert pv.exists() and pv.stat().st_size > 1000
    pngs = EX.title_pngs(info["titel"], projekt.dirs["titel"], projekt.dirs["tmp"], 1280, 720, projekt.titelstil())
    assert len(pngs) == 2 and all(p.exists() for p, _, _ in pngs)
    g = projekt.stil_galerie("marker", "", "#ff3366")
    assert g.exists() and g.stat().st_size > 1000


def _hoehe(rgba):
    rows = (rgba[..., 3] > 20).any(axis=1).nonzero()[0]
    return rows[-1] - rows[0] if len(rows) else 0


def _text_ausdehnung(rgba):
    import numpy as np
    m = rgba[..., 3] > 200
    cols, rows = np.where(m.any(axis=0))[0], np.where(m.any(axis=1))[0]
    return (cols[-1] - cols[0], rows[-1] - rows[0]) if len(cols) else (0, 0)


def test_font_sizes(tmp_path):
    """Title and subtitle size can be set; a title that would be wider than the picture shrinks to fit."""
    klein = TI.render("Freizeit", "Sommer 2026", 960, 540, {"stil": "klar", "groesse": 60, "groesse_unter": 60}, "titel", tmp_path)
    gross = TI.render("Freizeit", "Sommer 2026", 960, 540, {"stil": "klar", "groesse": 160, "groesse_unter": 60}, "titel", tmp_path)
    unter = TI.render("Freizeit", "Sommer 2026", 960, 540, {"stil": "klar", "groesse": 60, "groesse_unter": 160}, "titel", tmp_path)
    wk, hk = _text_ausdehnung(klein)
    wg, hg = _text_ausdehnung(gross)
    wu, hu = _text_ausdehnung(unter)
    assert wg > wk * 1.8 and hg > hk * 1.3
    assert hu > hk * 1.2
    lang = TI.render("Ein sehr sehr langer Titel für die Musizierfreizeit", "", 960, 540,
                     {"stil": "klar", "groesse": 200}, "titel", tmp_path)
    w, _ = _text_ausdehnung(lang)
    assert w <= 960 * 0.93


def test_bold_or_not(tmp_path):
    fett = TI.render("Freizeit 2026", "Sommer", 960, 540, {"stil": "klar", "fett": True, "fett_unter": True}, "titel", tmp_path)
    duenn = TI.render("Freizeit 2026", "Sommer", 960, 540, {"stil": "klar", "fett": False, "fett_unter": False}, "titel", tmp_path)
    ink = lambda a: int((a[..., 3] > 200).sum())   # noqa: E731
    assert ink(fett) > ink(duenn) * 1.1
