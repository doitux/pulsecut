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
