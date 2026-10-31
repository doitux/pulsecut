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


def test_insert_another_clip_of_the_scene(projekt):
    """Step 9: take another clip of the same scene and put it right after the selected shot."""
    prepare(projekt)
    tl, _ = projekt.relayout()
    n0 = len(tl)
    frei = [(s, c) for s in tl for c in projekt.szenen_clips(s["id"])["clips"] if c["frei"]]
    print("shots with free material in their scene:", len({s["id"] for s, _ in frei}), "of", len(tl))
    sh, pick = next(((s, c) for s, c in frei if c["name"] != s["clip"]), frei[0])
    r = projekt.shot_einfuegen(sh["id"], pick["name"])
    assert r["ok"], r
    tl, diff = projekt.relayout()
    ids = [s["id"] for s in tl]
    new = tl[ids.index(sh["id"]) + 1]
    assert new["id"] == r["id"] and new["clip"] == pick["name"] and new["lock"]
    assert new["szene"] == sh["szene"]
    assert problems(projekt, allow_unchrono=True) == ([], 0)       # film length unchanged, no overlaps
    assert abs(len(tl) - n0) <= 2
    projekt.plan(keep_locked=True)                                  # locked: survives re-planning (in its scene)
    tl, _ = projekt.relayout()
    ids = [s["id"] for s in tl]
    assert r["id"] in ids and sh["id"] in ids
    # automatic choice within the scene
    r2 = projekt.shot_einfuegen(sh["id"])
    assert r2["ok"] or r2.get("fehler")


def _ids(pr):
    tl, _ = pr.relayout()
    return [s["id"] for s in tl], tl


def test_delete_moves_up_and_distributes(projekt):
    """Deleting in step 9: the shots behind move up, nothing similar from the same clip takes the place, everything
    before the deleted shot counts as finished and stays exactly as it was."""
    prepare(projekt)
    ids, tl = _ids(projekt)
    i = len(tl) // 3
    sh = dict(tl[i])
    before = [(s["id"], s["clip"], s["src"], s["k"]) for s in tl[:i]]
    opts = projekt.entfernen_optionen(sh["id"])
    assert set(opts) >= {"rest", "nachbar", "kuerzer"} and opts["kuerzer"]["ok"]
    assert _ids(projekt)[0] == ids                                   # asking changes nothing
    r = projekt.shot_entfernen(sh["id"], ausgleich="rest")
    assert r["ok"]
    ids2, tl2 = _ids(projekt)
    assert sh["id"] not in ids2
    assert [(s["id"], s["clip"], s["src"], s["k"]) for s in tl2[:i]] == before
    assert projekt.d["fertig_bis"] == tl2[i - 1]["id"]
    assert tl2[i]["id"] == ids[i + 1]                                # the next one moved up
    a, b = sh["src"], sh["src"] + sh["dur"]
    assert not any(s["clip"] == sh["clip"] and s["src"] < b + 0.1 and s["src"] + s["dur"] > a - 0.1 for s in tl2)
    assert problems(projekt) == ([], 0)
    # re-planning and filling keep the finished part
    projekt.plan(keep_locked=True)
    projekt.auffuellen()
    assert [(s["id"], s["clip"], s["src"], s["k"]) for s in _ids(projekt)[1][:i]] == before
    assert problems(projekt) == ([], 0)


def test_delete_neighbour_longer_and_film_shorter(projekt):
    prepare(projekt)
    ids, tl = _ids(projekt)
    i = len(tl) // 2
    sh = dict(tl[i])
    tl = [dict(s) for s in tl]
    after_k = sum(int(s["k"]) for s in tl[i + 1:])
    n_before = len(tl)
    r = projekt.shot_entfernen(sh["id"], ausgleich="nachbar")
    assert r["ok"]
    tl2 = _ids(projekt)[1]
    grown = sum(int(s["k"]) for s in tl2[i:]) - after_k
    assert grown == int(sh["k"])                                     # the freed bars went to the shots behind it
    old_k = {s["id"]: int(s["k"]) for s in tl[i + 1:]}
    # the first following shot with room in its clip took them (if the very next clip is too short, the one after)
    gained = [s["id"] for s in tl2[i:] if int(s["k"]) > old_k.get(s["id"], 99)]
    assert gained and [s["id"] for s in tl2[i:]].index(gained[0]) <= 3
    assert len(tl2) == n_before - 1 and problems(projekt) == ([], 0)
    # film shorter: the music ends that many bars earlier, everything else stays
    N = len(projekt.layout.units) - 1
    ids3, tl3 = _ids(projekt)
    sh3 = dict(tl3[i + 2])
    keep = [(s["id"], round(s["src"], 1), s["k"]) for s in tl3 if s["id"] != sh3["id"]]
    projekt.shot_entfernen(sh3["id"], ausgleich="kuerzer")
    assert len(projekt.layout.units) - 1 == N - int(sh3["k"])
    assert [(s["id"], round(s["src"], 1), s["k"]) for s in _ids(projekt)[1]][:-1] == keep[:-1]   # (last one ends 0.3 s later)
    assert problems(projekt) == ([], 0) and projekt.timeline_info()["ende_weg"] == int(sh3["k"])
    projekt.ende_zuruecknehmen()
    assert len(projekt.layout.units) - 1 == N and problems(projekt) == ([], 0)


def test_finished_marker_and_shares(projekt):
    prepare(projekt)
    ids, tl = _ids(projekt)
    tl = [dict(s) for s in tl]
    projekt.shot_ton(tl[5]["id"], "aus")
    assert projekt.d["fertig_bis"] == tl[5]["id"]
    projekt.shot_ton(tl[2]["id"], "aus")                             # never moves back by itself
    assert projekt.d["fertig_bis"] == tl[5]["id"]
    assert projekt.fertig_setzen(tl[1]["id"])["fertig_bis"] == tl[1]["id"]
    assert [s["fertig"] for s in projekt.timeline_info()["shots"][:3]] == [True, True, False]
    projekt.fertig_setzen(None)
    assert projekt.timeline_info()["fertig_bis"] is None
    # deleting many shots of one keyword shifts the shares → a notice, which can be accepted or balanced
    assert projekt.timeline_info()["abweichungen"] == []
    zkw = {z["id"]: z["kw"] for z in projekt.scenes}
    kw = max(set(zkw.values()), key=lambda k: sum(1 for s in tl if zkw.get(s.get("szene")) == k))
    for s in [s for s in tl if zkw.get(s.get("szene")) == kw][:4]:
        projekt.shot_entfernen(s["id"], ausgleich="rest")
    dev = projekt.timeline_info()["abweichungen"]
    assert dev and any(d["kw"] == kw and d["diff"] < 0 for d in dev)
    projekt.fertig_setzen(None)
    r = projekt.anteile_ausgleichen()
    dev2 = projekt.timeline_info()["abweichungen"]
    if r["verbessert"]:
        assert sum(abs(d["diff"]) for d in dev2) < sum(abs(d["diff"]) for d in dev)
    else:                    # (the synthetic footage of that keyword may be used up)
        assert sum(abs(d["diff"]) for d in dev2) <= sum(abs(d["diff"]) for d in dev) + 1
    assert problems(projekt) == ([], 0)
    projekt.anteile_ok()
    assert projekt.timeline_info()["abweichungen"] == []
    assert problems(projekt) == ([], 0)


def test_balance_shares_moves_shots(projekt):
    """„Ausgleichen“: shots of an over-represented keyword are swapped for shots of an under-represented one."""
    prepare(projekt)
    tl = projekt.relayout()[0]
    ist = projekt.anteile_ist(tl)
    zkw = {z["id"]: z["kw"] for z in projekt.scenes}
    k = int(projekt.d["schnitt"].get("k") or 0) or projekt.k_default()
    proto = {"id": "neu", "clip": "", "src": 0.0, "dur": projekt.layout.unit_len() * k, "k": k}
    frei = [z["kw"] for z in projekt.scenes
            if PL.best_free_window(tl, proto, z["clips"], projekt.xf(), slack=projekt._slack(proto))]
    a = frei[0]
    b = max((kw for kw in ist if kw != a), key=lambda kw: ist[kw])
    basis = dict(ist)
    basis[a] += 40.0
    basis[b] -= 40.0
    projekt.d["anteile_basis"] = basis
    dev = projekt.timeline_info()["abweichungen"]
    assert {d["kw"] for d in dev} >= {a, b}
    r = projekt.anteile_ausgleichen()
    assert r["verbessert"]
    ist2 = projekt.anteile_ist(projekt.relayout()[0])
    assert ist2[a] > ist[a] and ist2[b] < ist[b]
    assert problems(projekt) == ([], 0)


def test_insert_previewed_clip_at_a_chosen_point(projekt):
    """Step 9, insert with preview: the suggested passage is what gets inserted; 'from here' takes that point – or the
    nearest free passage next to it when it is already in the film; undo takes it out again."""
    from pulsecut import planer as PL_
    prepare(projekt)
    tl, _ = projekt.relayout()
    d = None
    for s in tl:
        d0 = projekt.szenen_clips(s["id"])
        c = next((c for c in d0["clips"] if c["frei"] and c["dauer"] >= 4 * d0["laenge"]), None)
        if c:
            sh, d, pick = s, d0, c
            break
    assert d, "no clip with room in the test footage"
    L = d["laenge"]
    assert pick["proxy"].endswith(".webm") and pick["vorschlag"] is not None
    cl = projekt.clip_by_name()
    assert pick["belegt"] == [[round(s["src"], 2), round(s["src"] + s["dur"], 2)] for s in tl
                              if s["clip"] == pick["name"] and s["dur"] > 0]
    # 1) the suggested passage
    r = projekt.shot_einfuegen(sh["id"], pick["name"])
    assert r["ok"] and abs(r["src"] - pick["vorschlag"]) < 0.01, (r, pick["vorschlag"])
    projekt.rueckgaengig()
    assert r["id"] not in [s["id"] for s in projekt.relayout()[0]]
    # 2) "from here" at a free point: starts there (raster 0.25 s)
    tl, _ = projekt.relayout()
    belegt = [PL_.reserved(s, projekt.xf()) for s in tl if s["clip"] == pick["name"]]
    c = cl[pick["name"]]
    frei = [t / 4 for t in range(int(PL_.EDGE * 4) + 1, int((c.dur - L - 0.5) * 4))
            if not any(PL_.overlaps(t / 4 - 0.3, t / 4 + L + 0.3, a, b) for a, b in belegt)
            and not (c.excl and PL_.hits_excl(c, t / 4, t / 4 + L))]
    assert frei
    want = frei[len(frei) // 2]
    r = projekt.shot_einfuegen(sh["id"], pick["name"], src=want + 0.1)
    assert r["ok"] and abs(r["src"] - want) <= 0.25 + 1e-6, (r, want)
    tl, _ = projekt.relayout()
    assert problems(projekt, allow_unchrono=True) == ([], 0)
    # 3) "from here" inside that passage (now in the film): the nearest free passage, no overlap
    new = next(s for s in tl if s["id"] == r["id"])
    r2 = projekt.shot_einfuegen(r["id"], pick["name"], src=new["src"] + 0.2)
    if r2["ok"]:
        tl, _ = projekt.relayout()
        n2 = next(s for s in tl if s["id"] == r2["id"])
        assert not PL_.overlaps(*PL_.reserved(n2, projekt.xf()), *PL_.reserved(new, 0.0))
        assert problems(projekt, allow_unchrono=True) == ([], 0)
        projekt.rueckgaengig()
    projekt.rueckgaengig()
    assert r["id"] not in [s["id"] for s in projekt.relayout()[0]]
