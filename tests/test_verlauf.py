"""Undo/redo in the timeline (step 9): every edit can be taken back exactly, and done again."""
import random

import pytest

from conftest import prepare
from pulsecut import planer as PL


def probleme(pr):
    tl, diff = pr.relayout()
    hart = [p for p in PL.check(tl, pr.clip_by_name(), pr.xf(), allow_unchrono=True) if p["art"] in ("ueberlappung", "rand")]
    return hart, diff


def frisch(pr):
    prepare(pr)
    pr.verlauf = {"rueck": [], "vor": []}
    return pr.relayout()[0]


def pruefe_hin_und_zurueck(pr, op, name):
    vorher = pr._zustand()
    n = len(pr.verlauf["rueck"])
    op()
    nachher = pr._zustand()
    if nachher == vorher:
        assert len(pr.verlauf["rueck"]) == n, f"{name}: nothing changed, but an undo step was recorded"
        return False
    assert len(pr.verlauf["rueck"]) == n + 1, f"{name}: no undo step recorded"
    assert pr.verlauf["vor"] == []
    r = pr.rueckgaengig()
    assert r["ok"], (name, r)
    assert pr._zustand() == vorher, f"{name}: undo does not restore the previous state"
    assert probleme(pr) == ([], 0), name
    r = pr.wiederholen()
    assert r["ok"], (name, r)
    assert pr._zustand() == nachher, f"{name}: redo does not restore the state after the edit"
    assert probleme(pr)[0] == [], name
    return True


def test_every_edit_can_be_undone_and_redone(projekt):
    pr = projekt
    tl = frisch(pr)
    i = len(tl) // 3
    s = lambda j: pr.relayout()[0][j]   # noqa: E731
    cl = pr.clip_by_name()
    frei, frei_ziel = None, None            # a shot that can be slipped inside its clip without bumping into others
    for sh in tl:
        rg = PL.slip_range(tl, sh, cl[sh["clip"]], pr.xf())
        if rg["hi"] - rg["lo"] > 0.5:
            frei = sh
            frei_ziel = rg["hi"] if abs(rg["hi"] - sh["src"]) > 0.2 else rg["lo"]
            break
    assert frei is not None
    ops = [
        ("slip", lambda: pr.shot_slip(frei["id"], frei_ziel)),
        ("slip-force", lambda: pr.shot_slip(s(i + 1)["id"], cl[s(i + 1)["clip"]].dur / 2, force=True)),
        ("length", lambda: pr.shot_laenge(s(i + 2)["id"], int(s(i + 2)["k"]) * 2, force=True)),
        ("move", lambda: pr.shot_move(s(i + 3)["id"], i + 6)),
        ("other passage", lambda: pr.shot_anders(s(i + 4)["id"])),
        ("lock", lambda: pr.shot_sperren(s(i + 5)["id"], True)),
        ("unlock", lambda: pr.shot_sperren(s(i + 5)["id"], False)),
        ("sound off", lambda: pr.shot_ton(s(i + 6)["id"], "aus")),
        ("insert", lambda: pr.shot_einfuegen(s(i + 7)["id"])),
        ("remove rest", lambda: pr.shot_entfernen(s(i + 8)["id"], ausgleich="rest")),
        ("remove neighbour", lambda: pr.shot_entfernen(s(i + 9)["id"], ausgleich="nachbar")),
        ("remove shorter", lambda: pr.shot_entfernen(s(i + 10)["id"], ausgleich="kuerzer")),
        ("undo shortening", lambda: pr.ende_zuruecknehmen()),
        ("finished marker", lambda: pr.fertig_setzen(s(2)["id"])),
        ("shares ok", lambda: pr.anteile_ok()),
        ("balance", lambda: pr.anteile_ausgleichen()),
        ("fill", lambda: pr.auffuellen()),
        ("plan", lambda: pr.plan(keep_locked=True)),
        ("plan all", lambda: pr.plan(keep_locked=False)),
    ]
    changed = [name for name, op in ops if pruefe_hin_und_zurueck(pr, op, name)]
    print("changed something:", changed)
    for must in ("slip", "length", "move", "lock", "sound off", "remove rest", "remove neighbour", "remove shorter",
                 "undo shortening", "finished marker", "plan all"):
        assert must in changed, must


def test_failed_edit_records_nothing(projekt):
    pr = projekt
    tl = frisch(pr)
    cnt = {}
    for s in tl:
        cnt.setdefault(s["clip"], []).append(s)
    a, b = next(v for v in cnt.values() if len(v) >= 2)[:2]
    r = pr.shot_slip(a["id"], b["src"])                  # bumps into its neighbour: not done
    assert not r["ok"] and pr.verlauf["rueck"] == []


def test_long_random_sequence_back_and_forth(projekt):
    """50 random edits; then undo all of them one by one (each step must give exactly the state before that edit),
    then redo all of them again."""
    pr = projekt
    frisch(pr)
    rng = random.Random(7)
    cl = pr.clip_by_name()
    staende = [pr._zustand()]
    for _ in range(50):
        tl, _ = pr.relayout()
        s = rng.choice(tl)
        op = rng.choice(["slip", "slipf", "len", "move", "anders", "weg", "wegn", "wegk", "lock", "ton", "plus",
                         "fertig", "fill"])
        if op == "slip":
            pr.shot_slip(s["id"], s["src"] + rng.uniform(-3, 3))
        elif op == "slipf":
            pr.shot_slip(s["id"], rng.uniform(0, cl[s["clip"]].dur), force=True)
        elif op == "len":
            pr.shot_laenge(s["id"], rng.choice([1, 2, 3, 4]), force=rng.random() < 0.5)
        elif op == "move":
            pr.shot_move(s["id"], rng.randrange(len(tl)))
        elif op == "anders":
            pr.shot_anders(s["id"])
        elif op in ("weg", "wegn", "wegk"):
            pr.shot_entfernen(s["id"], ausgleich={"weg": "rest", "wegn": "nachbar", "wegk": "kuerzer"}[op])
        elif op == "lock":
            pr.shot_sperren(s["id"], rng.random() < 0.6)
        elif op == "ton":
            pr.shot_ton(s["id"], rng.choice(["", "an", "aus"]))
        elif op == "plus":
            pr.shot_einfuegen(s["id"])
        elif op == "fertig":
            pr.fertig_setzen(rng.choice([None, s["id"]]))
        elif op == "fill":
            pr.auffuellen()
        assert probleme(pr)[0] == []
        z = pr._zustand()
        if z != staende[-1]:
            staende.append(z)
    n = len(staende) - 1
    assert len(pr.verlauf["rueck"]) == n and n >= 30
    for j in range(n, 0, -1):                              # all the way back
        assert pr.rueckgaengig()["ok"]
        assert pr._zustand() == staende[j - 1], f"undo step {n - j + 1}"
        assert probleme(pr) == ([], 0)
    assert not pr.rueckgaengig()["ok"]                     # nothing left
    for j in range(1, n + 1):                              # and forward again
        assert pr.wiederholen()["ok"]
        assert pr._zustand() == staende[j], f"redo step {j}"
    assert not pr.wiederholen()["ok"]
    # several steps at once, then a new edit drops the steps that could have been redone
    assert pr.rueckgaengig(5)["ok"] and pr._zustand() == staende[n - 5]
    assert len(pr.verlauf["vor"]) == 5
    pr.shot_ton(pr.relayout()[0][0]["id"], "aus")
    assert pr.verlauf["vor"] == []


def test_history_survives_reopening(projekt):
    from pulsecut.projekt import Projekt
    pr = projekt
    tl = frisch(pr)
    vorher = pr._zustand()
    pr.shot_entfernen(tl[5]["id"], ausgleich="rest")
    nachher = pr._zustand()
    p2 = Projekt(pr.ordner)
    assert [e["text"] for e in p2.verlauf["rueck"]] == ["Schnitt entfernt"]
    # once loaded (analysis, music, recognition), the step can be undone in the reopened project
    p2.clips, p2.tracks, p2.scenes, p2.layout = pr.clips, pr.tracks, pr.scenes, pr.layout
    assert p2.rueckgaengig()["ok"] and p2._zustand() == vorher
    assert p2.wiederholen()["ok"] and p2._zustand() == nachher


def test_no_undo_into_a_changed_basis(projekt):
    """After the music length or the recognition changed, old states no longer fit: undo is refused, not broken."""
    pr = projekt
    tl = frisch(pr)
    pr.shot_ton(tl[3]["id"], "aus")
    assert pr.verlauf["rueck"]
    pr.d["ziel_dauer"] = pr.layout.D - 20
    pr.d["kuerzen"] = {t["datei"]: "hinten" for t in pr.tracks}
    pr.update_layout()
    r = pr.rueckgaengig()
    assert not r["ok"] and "nicht mehr" in r["fehler"]
    assert pr.verlauf == {"rueck": [], "vor": []}
    pr.d["ziel_dauer"] = None
    pr.d["kuerzen"] = {}
    pr.update_layout()


@pytest.mark.parametrize("lang", ["de", "en"])
def test_history_texts(projekt, lang):
    from pulsecut.i18n import set_lang
    pr = projekt
    tl = frisch(pr)
    set_lang(lang, persist=False)
    try:
        pr.shot_entfernen(tl[4]["id"], ausgleich="nachbar")
        txt = pr.timeline_info()["verlauf"]["rueck"][0]
        assert txt.startswith("Schnitt entfernt (bei " if lang == "de" else "Shot removed (at ")
    finally:
        set_lang("de", persist=False)
