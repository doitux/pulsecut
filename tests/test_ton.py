"""Original sound: only atmosphere (laughter, applause, cheering, groups) and never where music plays;
per-clip on/off; the music is lowered softly underneath (or not)."""
import xml.etree.ElementTree as ET

import gen_clips
from conftest import prepare
from pulsecut import export as EX

AUDIO = {gen_clips.clip_name(c[0], c[6]): c[2] for c in gen_clips.clips}   # file → kind of sound in the clip


def planned(pr):
    info = pr.timeline_info()
    pr.atmo_plan(info["shots"])
    return info["shots"]


def test_atmosphere_only_without_music(projekt):
    prepare(projekt)
    shots = planned(projekt)
    with_sound = [s for s in shots if s["atmo"]]
    kinds = {AUDIO[s["clip"]] for s in with_sound}
    print("original sound in", len(with_sound), "shots:", sorted(kinds))
    assert with_sound, "no original sound chosen at all"
    assert "musik" not in kinds, "original sound where music plays"
    assert kinds <= {"lachen", "applaus", "jubel", "gruppe", "sprache", "bus", "leise"}


def test_music_only_and_clip_override(projekt):
    prepare(projekt, originalton="aus")
    assert not any(s["atmo"] for s in planned(projekt))
    prepare(projekt)
    chosen = {s["clip"] for s in planned(projekt) if s["atmo"]}
    off = sorted(chosen)[0]
    projekt.set_clip(off, ton="aus")
    assert not any(s["atmo"] and s["clip"] == off for s in planned(projekt))
    projekt.set_clip(off, ton="")
    music_clip = next(s["clip"] for s in planned(projekt) if AUDIO[s["clip"]] == "musik")
    projekt.set_clip(music_clip, ton="an")   # "on" still never plays over music
    assert not any(s["atmo"] and s["clip"] == music_clip for s in planned(projekt))


def test_shot_override_in_the_timeline(projekt):
    """Step 9: per shot on/off, kept through re-planning (the shot gets locked), wins over the clip setting."""
    prepare(projekt)
    shots = planned(projekt)
    on = next(s for s in shots if s["atmo"])
    assert on["ton_info"]["grund"] == "dabei"
    assert projekt.shot_ton(on["id"], "aus")["ok"]
    after = {s["id"]: s for s in planned(projekt)}
    assert after[on["id"]]["atmo"] is None and after[on["id"]]["ton_info"]["grund"] == "aus_schnitt"
    assert after[on["id"]]["lock"]
    projekt.plan(keep_locked=True)                     # survives re-planning
    after = {s["id"]: s for s in planned(projekt)}
    assert after[on["id"]]["ton"] == "aus" and after[on["id"]]["atmo"] is None
    # a quiet shot without anything atmospheric: "on" takes it in
    quiet = next(s for s in planned(projekt) if not s["atmo"] and s["ton_info"]["grund"] == "unauffaellig")
    projekt.shot_ton(quiet["id"], "an")
    assert {s["id"]: s for s in planned(projekt)}[quiet["id"]]["atmo"]
    # music in the video: automatic never, "on" in the timeline is the user's decision
    mus = next(s for s in planned(projekt) if AUDIO[s["clip"]] == "musik")
    assert mus["ton_info"]["grund"] == "musik" and not mus["atmo"]
    projekt.shot_ton(mus["id"], "an")
    m2 = {s["id"]: s for s in planned(projekt)}[mus["id"]]
    assert m2["atmo"] and m2["ton_info"]["musik"]
    # the shot setting beats the clip setting
    projekt.set_clip(mus["clip"], ton="aus")
    assert {s["id"]: s for s in planned(projekt)}[mus["id"]]["atmo"]
    projekt.set_clip(mus["clip"], ton="")
    projekt.shot_ton(mus["id"], "")                    # back to automatic
    assert not {s["id"]: s for s in planned(projekt)}[mus["id"]]["atmo"]
    # "music only" switches everything off
    projekt.d["schnitt"]["originalton"] = "aus"
    assert all(not s["atmo"] and s["ton_info"]["grund"] == "aus_gesamt" for s in planned(projekt))
    projekt.d["schnitt"]["originalton"] = "auto"


def test_ducking_curve():
    spans = EX.duck_spans([{"pos": 100, "len": 200, "fi": 30, "fo": 40}, {"pos": 300, "len": 100, "fi": 15, "fo": 40}])
    assert spans == [(100, 130, 360, 400)]
    assert EX.duck_at(90, spans, 6) == 0 and EX.duck_at(200, spans, 6) == 6
    assert 0 < EX.duck_at(115, spans, 6) < 6 and 0 < EX.duck_at(380, spans, 6) < 6
    assert EX.duck_expr(spans, 0) is None and "pow(10" in EX.duck_expr(spans, 6)


def music_levels(path):
    root = ET.parse(path).getroot()
    out = []
    for f in root.iter("filter"):
        props = {p.get("name"): p.text for p in f.iter("property")}
        if props.get("mlt_service") == "volume" and props.get("kdenlive_id") == "volume" and "level" in props:
            out.append(props["level"])
    return out


def test_kdenlive_music_lowered_under_original_sound(projekt, tmp_path):
    prepare(projekt, absenken=6)
    assert any(s["atmo"] for s in planned(projekt))
    EX.write_project(projekt, tmp_path / "a.kdenlive")
    prepare(projekt, absenken=0)
    EX.write_project(projekt, tmp_path / "b.kdenlive")
    lowered = [lv for lv in music_levels(tmp_path / "a.kdenlive") if "=-6.0" in lv]
    assert lowered, "music is not lowered anywhere"
    assert not [lv for lv in music_levels(tmp_path / "b.kdenlive") if "=-6.0" in lv]
