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


def test_analysis_quiet_and_boost(media, tmp_path):
    """Fresh analysis with one quiet worker, switched to full power while it runs."""
    import shutil
    import threading
    from pulsecut.projekt import Job, Projekt
    vid, mus = tmp_path / "v", tmp_path / "m"
    vid.mkdir()
    mus.mkdir()
    for name in sorted(p.name for p in media.RAW.glob("VID_2026071*_1*.mp4"))[:4]:
        shutil.copy2(media.RAW / name, vid / name)
    shutil.copy2(media.MUSIK / "01 Morning Groove.mp3", mus)
    pr = Projekt.erstellen("Boost", vid, mus, tmp_path / "p")
    assert pr.boost is False
    threading.Timer(1.0, lambda: setattr(pr, "boost", True)).start()
    job = Job("analyse")
    pr.analyse_job(job)
    assert len(pr.clips) == 4 and all(c.ana for c in pr.clips)
    assert all((pr.dirs["proxy"] / f"{c.hash}.webm").exists() for c in pr.clips)


def test_excluded_clips_and_new_keyword(projekt):
    prepare(projekt)
    out = projekt.clips[13]
    projekt.set_clip(out.name, prio="raus")
    projekt.compute_erkennung()
    assert all(c.name != out.name for z in projekt.scenes for c in z["clips"])
    assert projekt.erkennung_info()["ausgeschlossen"] == 1
    # a wrongly sorted scene gets its own new keyword, placed where it happened in the course of events
    z = next(z for z in projekt.scenes if len(z["clips"]) >= 1 and z["kw"] == projekt.d["stichworte"][3]["id"])
    new = projekt.neues_stichwort("Abschlussparty", list(z["clips"]))
    ids = [k["id"] for k in projekt.d["stichworte"]]
    assert new["id"] in ids and len(ids) == 11
    assert all(c.kw == new["id"] for c in z["clips"])
    assert any(s["kw"] == new["id"] for s in projekt.scenes)
    assert projekt.erk["ki"], "recognition fell back to no-AI mode after adding a keyword"
    projekt.plan(keep_locked=False)
    assert problems(projekt) == ([], 0)
