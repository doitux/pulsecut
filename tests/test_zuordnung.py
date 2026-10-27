"""Step 6: moving single clips or whole scenes to another keyword by hand – and back to automatic."""
import numpy as np
import pytest

from conftest import prepare
from pulsecut import erkennung as ER
from pulsecut import planer as PL


def zuordnung(pr):
    return {c.name: c.kw for c in pr.clips if c.prio != "raus"}


def leeres_stichwort(pr, name="Abmarsch zum Bus", pos=1):
    """Inserts a keyword the (simulated) AI finds nothing for – like 'Abmarsch zum Bus' in a real project."""
    kws = [dict(k) for k in pr.d["stichworte"]]
    kws.insert(pos, {"id": "kabm", "name": name, "text": name, "wiederkehrend": False, "gewicht": 1.0})
    pr.set_stichworte(kws)
    v = np.random.default_rng(7).normal(size=512).astype(np.float32)
    pr.cache["texte"][ER.kw_text(pr.d["stichworte"][pos])] = (v / np.linalg.norm(v)).tolist()
    pr.compute_erkennung()
    return "kabm"


def test_move_one_clip_into_an_empty_keyword_and_back(projekt):
    pr = projekt
    prepare(pr)
    kid = leeres_stichwort(pr)
    assert not any(z["kw"] == kid for z in pr.scenes), "the new keyword should start without scenes"
    vorher = zuordnung(pr)
    # a scene of a neighbouring keyword with several clips – one of them really belongs to the empty keyword
    ids = [k["id"] for k in pr.d["stichworte"]]
    nachbarn = {ids[0], ids[2]}
    z = next(z for z in pr.scenes if z["kw"] in nachbarn and len(z["clips"]) >= 2)
    alt_kw, clip, rest = z["kw"], z["clips"][-1], [c.name for c in z["clips"][:-1]]
    assert pr.clips_kw([clip.name], kid) == 1
    assert clip.kw == kid and clip.kat_manuell == kid
    assert pr.d["clips"][clip.name]["kat"] == kid          # saved with the project
    # the old scene is split: the other clips keep their keyword, the moved clip forms a scene of its own
    cl = pr.clip_by_name()
    assert all(cl[n].kw == alt_kw for n in rest)
    neu = [s for s in pr.scenes if s["kw"] == kid]
    assert len(neu) == 1 and [c.name for c in neu[0]["clips"]] == [clip.name]
    info = pr.erkennung_info()
    g = next(g for g in info["gruppen"] if g["kw"] == kid)
    assert g["szenen"] == 1 and g["clips"] == 1
    s = next(s for s in info["szenen"] if s["kw"] == kid)
    c = s["clipliste"][0]
    assert c["kw"] == kid and c["kw_manuell"] == kid and c["proxy"].endswith(".webm") and isinstance(s["ord"], int)
    # nothing else changed
    nachher = zuordnung(pr)
    assert {n for n in nachher if nachher[n] != vorher[n]} == {clip.name}
    # stays like that when the recognition runs again (e.g. after a new keyword or a changed video)
    pr.compute_erkennung()
    assert pr.clip_by_name()[clip.name].kw == kid
    # the film is planned with it and still keeps all rules
    pr.d["timeline"] = None
    pr.plan(keep_locked=False)
    tl, _ = pr.relayout()
    assert [p["art"] for p in PL.check(tl, pr.clip_by_name(), pr.xf())] == []
    # back to automatic: exactly the assignment from before
    assert pr.clips_kw([clip.name], "") == 1
    assert clip.name not in pr.d["clips"]
    assert zuordnung(pr) == vorher


def test_gather_several_clips_and_whole_scene(projekt):
    pr = projekt
    prepare(pr)
    kid = leeres_stichwort(pr)
    vorher = zuordnung(pr)
    # gather clips from two different scenes in one go ("⇆ Clips hierher holen")
    zs = [z for z in pr.scenes if z["kw"] != kid][:2]
    namen = [zs[0]["clips"][-1].name, zs[1]["clips"][0].name]
    assert pr.clips_kw(namen + ["gibt es nicht.mp4"], kid) == 2   # unknown names are ignored
    assert sorted(c.name for s in pr.scenes if s["kw"] == kid for c in s["clips"]) == sorted(namen)
    # whole scene to another keyword and back
    z = next(z for z in pr.scenes if z["kw"] not in (kid,) and len(z["clips"]) >= 2)
    ziel = next(k["id"] for k in pr.d["stichworte"] if k["id"] not in (z["kw"], kid))
    alle = [c.name for c in z["clips"]]
    pr.clips_kw(alle, ziel)
    assert all(pr.clip_by_name()[n].kw == ziel for n in alle)
    pr.clips_kw(alle + namen, "")
    assert zuordnung(pr) == vorher
    assert not any(u.get("kat") for u in pr.d["clips"].values())


def test_unknown_keyword_is_refused(projekt):
    pr = projekt
    prepare(pr)
    vorher = zuordnung(pr)
    with pytest.raises(RuntimeError):
        pr.clips_kw([pr.clips[0].name], "gibtsnicht")
    assert zuordnung(pr) == vorher and not pr.d["clips"]


def test_other_settings_of_a_clip_survive(projekt):
    pr = projekt
    prepare(pr)
    c = next(c for c in pr.clips if c.prio != "raus")
    pr.set_clip(c.name, prio="hoch", ton="an")
    k = next(k["id"] for k in pr.d["stichworte"] if k["id"] != c.kw)
    pr.clips_kw([c.name], k)
    pr.clips_kw([c.name], "")
    assert pr.d["clips"][c.name] == {"prio": "hoch", "ton": "an"}
