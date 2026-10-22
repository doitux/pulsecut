"""Recognition, planning and timeline editing on the synthetic camp footage (simulated AI)."""
from conftest import prepare
from fake import true_kw
from pulsecut import planer as PL


def problems(pr, allow_unchrono=False):
    tl, diff = pr.relayout()
    return [p["art"] for p in PL.check(tl, pr.clip_by_name(), pr.xf(), allow_unchrono=allow_unchrono)], diff


def test_analysis(projekt):
    assert len(projekt.clips) == 38
    wa = [c for c in projekt.clips if c.name.startswith("WhatsApp")]
    assert len(wa) == 1 and wa[0].time_source == "Dateiname"   # no metadata: time taken from the file name
    assert len(projekt.tracks) == 3
    for t in projekt.tracks:
        assert 60 < t["bpm"] < 170


def test_recognition_follows_description(projekt):
    lab = prepare(projekt)
    kws = projekt.d["stichworte"]
    assert len(kws) == 10
    wrong = []
    for c in projekt.clips:
        k = true_kw(lab[c.name])
        if k >= 0 and c.kw != kws[k]["id"]:
            wrong.append((lab[c.name], c.kw))
    assert len(wrong) <= 1, wrong
    fragen = projekt.erk["fragen"]
    assert any(f["id"] == "party" for f in fragen), fragen


def test_plan_obeys_hard_rules(projekt):
    prepare(projekt)
    probs, diff = problems(projekt)
    assert probs == [] and diff == 0
    tl = projekt.d["timeline"]
    assert len(tl) > 20
    # every shot of a scene in chronological order, never two overlapping passages of one clip
    cl = projekt.clip_by_name()
    by_scene = {}
    for s in tl:
        by_scene.setdefault(s["szene"], []).append(s)
    for shots in by_scene.values():
        keys = [(cl[s["clip"]].start, s["src"]) for s in shots]
        assert keys == sorted(keys)


def test_crossfade_plan(projekt):
    prepare(projekt, uebergang="blende", blende=0.8)
    assert problems(projekt) == ([], 0)


def test_motion_option_keeps_rules(projekt):
    prepare(projekt, bewegung=True)
    probs, diff = problems(projekt, allow_unchrono=True)
    assert probs == [] and diff == 0


def test_edits(projekt):
    prepare(projekt)
    tl, _ = projekt.relayout()
    same = {}
    for s in tl:
        same.setdefault(s["clip"], []).append(s)
    a, b = sorted(next(v for v in same.values() if len(v) >= 2), key=lambda s: s["src"])[:2]
    r = projekt.shot_slip(a["id"], b["src"])
    assert not r["ok"] and r["kollision"]
    r = projekt.shot_slip(a["id"], b["src"], force=True)
    assert r["ok"]
    assert any(s["id"] == a["id"] and s["lock"] for s in projekt.d["timeline"])
    assert problems(projekt) == ([], 0)

    s0 = projekt.d["timeline"][5]
    projekt.shot_laenge(s0["id"], int(s0["k"]) * 2, force=True)
    assert problems(projekt) == ([], 0)
    projekt.shot_move(projekt.d["timeline"][3]["id"], 0)
    assert problems(projekt, allow_unchrono=True) == ([], 0)
    removed = projekt.d["timeline"][8]
    projekt.shot_entfernen(removed["id"])
    assert all(s["id"] != removed["id"] for s in projekt.d["timeline"])
    assert problems(projekt, allow_unchrono=True) == ([], 0)
    projekt.shot_anders(projekt.d["timeline"][10]["id"])
    assert problems(projekt, allow_unchrono=True) == ([], 0)

    locked = {s["id"] for s in projekt.d["timeline"] if s.get("lock")}
    projekt.plan(keep_locked=True)
    assert locked <= {s["id"] for s in projekt.d["timeline"]}
    assert problems(projekt, allow_unchrono=True) == ([], 0)


def test_scene_weighting_and_order(projekt):
    prepare(projekt)
    kws = {k["name"]: k["id"] for k in projekt.d["stichworte"]}
    foto, konzert = kws["Gruppenfoto"], kws["Abschlusskonzert"]
    projekt.block_verschieben(foto, konzert)
    order = [z["kw"] for z in projekt.scenes]
    assert max(i for i, k in enumerate(order) if k == konzert) < min(i for i, k in enumerate(order) if k == foto)
    z = next(z for z in projekt.scenes if z["kw"] == kws["Freizeit Fußball"])
    projekt.set_scene(z["id"], menge="raus")
    projekt.plan(keep_locked=False)
    assert all(s["szene"] != z["id"] for s in projekt.d["timeline"])
    assert problems(projekt) == ([], 0)
