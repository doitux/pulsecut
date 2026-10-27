"""Step 7: the weighting slider also takes weaker passages above 1×, "Important" clips always may; hints at the slider."""
import pytest

from conftest import prepare
from pulsecut import planer as PL


def kw_id(pr, name):
    return next(k["id"] for k in pr.d["stichworte"] if k["name"] == name)


def gewicht(pr, kid, w):
    for k in pr.d["stichworte"]:
        if k["id"] == kid:
            k["gewicht"] = float(w)


@pytest.fixture
def schlecht(projekt):
    """Makes all clips of one keyword 'bad' (blurry/shaky everywhere) – and restores them afterwards."""
    pr = projekt
    prepare(pr)
    kid = kw_id(pr, "Gruppenfoto")
    clips = [c for z in pr.scenes if z["kw"] == kid for c in z["clips"]]
    alt = [(c, c.good_sec) for c in clips]
    for c in clips:
        c.good_sec = 0.0
    yield pr, kid, clips
    for c, g in alt:
        c.good_sec = g


def test_capacity_grows_with_the_slider(projekt):
    pr = projekt
    prepare(pr)
    p = pr.make_planer()
    L = p.L_of(p.k)
    for z in pr.scenes:
        caps = []
        for w in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            p.w[z["kw"]] = w
            caps.append(p.capacity(z, L))
        assert caps == sorted(caps), (z["id"], caps)
        assert caps[0] == caps[1] == p.capacity(z, L, r=0.0)       # up to 1×: only good passages, as before
        assert caps[-1] == p.capacity(z, L, r=1.0)                 # 3×: everything that fits


def test_bad_material_only_above_1x_or_when_important(schlecht):
    pr, kid, clips = schlecht
    v = pr.anteile_vorschau()
    assert v["kw"].get(kid, 0) == 0                          # 1×: nothing good there → nothing in the film
    assert v["material"][kid]["art"] == "limit" and not v["material"][kid]["schwach"]
    sek = {}
    for w in (2.0, 3.0):
        gewicht(pr, kid, w)
        v = pr.anteile_vorschau()
        sek[w] = v["kw"].get(kid, 0)
        assert sek[w] > 0 and v["material"][kid]["schwach"]
    assert sek[3.0] >= sek[2.0]
    # back at 1×, one clip set to "Important": it may give its weaker passages
    gewicht(pr, kid, 1.0)
    pr.set_clip(clips[0].name, prio="hoch")
    v = pr.anteile_vorschau()
    assert v["kw"].get(kid, 0) > 0 and v["material"][kid]["schwach"]
    # and the film is planned with it, keeping all rules
    gewicht(pr, kid, 3.0)
    pr.d["timeline"] = None
    pr.plan(keep_locked=False)
    tl, _ = pr.relayout()
    zkw = {z["id"]: z["kw"] for z in pr.scenes}
    assert any(zkw.get(s.get("szene")) == kid for s in tl)
    assert [x["art"] for x in PL.check(tl, pr.clip_by_name(), pr.xf())] == []


def test_maximum_and_limit_hints(projekt):
    pr = projekt
    prepare(pr)
    v = pr.anteile_vorschau()
    for kid, m in v["material"].items():
        assert m["n"] <= m["max_n"]
        assert (m["art"] == "max") == (m["n"] >= m["max_n"] > 0)
    # a keyword with little material: at 3× it is at its maximum – the hint says so and more weight changes nothing
    kid = kw_id(pr, "Abreise Bus")
    gewicht(pr, kid, 3.0)
    v = pr.anteile_vorschau()
    assert v["material"][kid]["art"] == "max"
    s3 = v["kw"][kid]
    p = pr.make_planer()
    L = p.L_of(p.k)
    assert s3 == pytest.approx(v["material"][kid]["max_n"] * L)
    # plenty of material: higher weight → more seconds, incl. weaker passages
    kid = kw_id(pr, "Proben Registern")
    s1 = pr.anteile_vorschau()["kw"][kid]
    gewicht(pr, kid, 3.0)
    v = pr.anteile_vorschau()
    assert v["kw"][kid] > s1 and v["material"][kid]["schwach"]
    # weight 0: no hint at all
    gewicht(pr, kid, 0.0)
    assert kid not in pr.anteile_vorschau()["material"]


def test_planned_shots_per_scene(projekt):
    pr = projekt
    prepare(pr)
    v = pr.anteile_vorschau()
    assert set(v["szene"]) == {z["id"] for z in pr.scenes}
    p = pr.make_planer()
    L = p.L_of(p.k)
    for z in pr.scenes:
        n, sek = v["szene"][z["id"]]
        assert n >= 0 and sek == pytest.approx(n * L, abs=0.06)
    tot = {}
    for z in pr.scenes:
        tot[z["kw"]] = tot.get(z["kw"], 0) + v["szene"][z["id"]][1]
    for kid, s in v["kw"].items():
        assert s == pytest.approx(tot[kid], abs=0.5)
