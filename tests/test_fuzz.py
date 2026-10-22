"""Random editing sequences: after every operation the hard rules must still hold and edited shots must survive.

    PULSECUT_FUZZ_STEPS=600 PULSECUT_FUZZ_SEEDS=1,2,3 pytest tests/test_fuzz.py
"""
import os
import random

import pytest

from conftest import prepare
from pulsecut import planer as PL

STEPS = int(os.environ.get("PULSECUT_FUZZ_STEPS", "120"))
SEEDS = [int(x) for x in os.environ.get("PULSECUT_FUZZ_SEEDS", "1").split(",")]
MODES = [("hart", 0.5, False), ("blende", 0.6, False), ("blende", 1.0, True)]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("mode", MODES, ids=lambda m: f"{m[0]}-{m[1]}-{'motion' if m[2] else 'chrono'}")
def test_random_edits(projekt, seed, mode):
    pr = projekt
    prepare(pr, uebergang=mode[0], blende=mode[1], bewegung=mode[2])
    rng = random.Random(seed * 1000 + MODES.index(mode))
    cl = pr.clip_by_name()
    for step in range(STEPS):
        tl, _ = pr.relayout()
        s = rng.choice(tl)
        op = rng.choice(["slip", "slip", "slipf", "len", "lenf", "move", "anders", "weg", "lock", "plan", "fill"])
        res = None
        if op == "slip":
            res = pr.shot_slip(s["id"], s["src"] + rng.uniform(-4, 4))
        elif op == "slipf":
            res = pr.shot_slip(s["id"], rng.uniform(0, cl[s["clip"]].dur), force=True)
        elif op == "len":
            res = pr.shot_laenge(s["id"], rng.choice([1, 2, 3, 4, 6]))
        elif op == "lenf":
            res = pr.shot_laenge(s["id"], rng.choice([2, 4, 6]), force=True)
        elif op == "move":
            pr.shot_move(s["id"], rng.randrange(len(tl)))
        elif op == "anders":
            res = pr.shot_anders(s["id"])
        elif op == "weg":
            pr.shot_entfernen(s["id"])
        elif op == "lock":
            pr.shot_sperren(s["id"], rng.random() < 0.5)
        elif op == "plan":
            pr.plan(keep_locked=True)
        elif op == "fill":
            pr.auffuellen()
        tl, diff = pr.relayout()
        where = f"step {step} after {op} on {s['id']}"
        if res and res.get("ok") and op in ("slip", "slipf", "len", "lenf", "anders"):
            assert any(x["id"] == s["id"] for x in tl), f"{where}: edited shot disappeared"
        probs = PL.check(tl, cl, pr.xf(), allow_unchrono=mode[2])
        hard = [p for p in probs if p["art"] in ("ueberlappung", "rand")]
        assert not hard, f"{where}: {hard}"
        assert diff == 0, f"{where}: timeline length differs from the music by {diff} units"
        if not mode[2]:
            assert not [p for p in probs if p["art"] == "chronologie"], f"{where}: chronology broken"
