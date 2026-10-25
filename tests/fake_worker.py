"""Simulated AI worker for tests (same interface as pulsecut/ki_worker.py)."""
import json, sys, re, hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake import labels, BESCHREIBUNG, DESCRIPTION_EN
CONCEPTS = [("REGISTERPROBE", r"registerprobe|dirigent|sectional|conductor"),
            ("ANREISE", r"\bbus\b.*\ban\b|anreise|ankunft|jugendherberge|arrives|youth hostel"),
            ("ANMELDUNG", r"anmeldung|armb|anwesenheit|registration|wristband"), ("KENNENLERN", r"kennenlern|get-to-know"),
            ("PROBE", r"probe|orchester|rehears"), ("AUSFLUG", r"ausflug|museum|trip"),
            ("KONZERT", r"konzert|auftritt|concert"), ("GRUPPENFOTO", r"gruppenfoto|group photo"),
            ("ABREISE", r"abreise|abschied|departure"), ("DISCO", r"disco|party"),
            ("FREIZEIT", r"freizeit|fußball|tischtennis|free time|football")]
def vec(name):
    rng = np.random.default_rng(int(hashlib.md5(name.encode()).hexdigest()[:8], 16))
    v = rng.normal(size=512).astype(np.float32); return v / np.linalg.norm(v)
def concept_of_label(lab):
    L = lab.upper()
    for c, _ in CONCEPTS:
        if L.startswith(c) or (c in L and c != "PROBE") or (c == "PROBE" and L.startswith("PROBE")):
            return c
    if "MUSEUM" in L: return "AUSFLUG"
    return "FREIZEIT"
def concept_of_text(t):
    t = t.lower()
    for c, rx in CONCEPTS:
        if re.search(rx, t): return c
    return "TEXT:" + t
job = json.loads(Path(sys.argv[1]).read_text())
lab = labels()
total = sum(len(a.get("items", [])) or 1 for a in job["aufgaben"]); done = 0
for a in job["aufgaben"]:
    if a["art"] == "bilder":
        print("MODELL Bild (simuliert)", flush=True)
        for it in a["items"]:
            name = Path(it["key"].split("|")[0]).name
            base = vec(concept_of_label(lab.get(name, "FREIZEIT")))
            rng = np.random.default_rng(len(it["frames"]))
            E = base[None] * 0.32 + rng.normal(size=(len(it["frames"]), 512)).astype(np.float32) * 0.03
            E /= np.linalg.norm(E, axis=1, keepdims=True)
            np.save(it["out"] + ".tmp.npy", E.astype(np.float16)); Path(it["out"] + ".tmp.npy").replace(it["out"])
            done += 1; print(f"FORTSCHRITT {done} {total}", flush=True)
    elif a["art"] == "texte":
        np.save(a["out"], np.stack([vec(concept_of_text(t)) for t in a["texte"]]))
        done += 1; print(f"FORTSCHRITT {done} {total}", flush=True)
    elif a["art"] == "ton":
        with open(a["out"], "a") as f:
            for it in a["items"]:
                f.write(json.dumps({"key": it["key"], "ton": {"t": [0.0], "fenster": 10.0, "musik": [0.1], "applaus": [0.0], "lachen": [0.0], "jubel": [0.0], "gruppe": [0.0], "sprache": [0.0]}}) + "\n")
                done += 1; print(f"FORTSCHRITT {done} {total}", flush=True)
    elif a["art"] == "sprache":
        import time
        print("SCHRITT laden", flush=True); time.sleep(0.6)
        print("SCHRITT erkennen", flush=True); print("ERKENNE 1.0 2.0", flush=True); time.sleep(0.8)
        print("ERKENNE 2.0 2.0", flush=True)
        Path(a["out"]).write_text((DESCRIPTION_EN if a.get("sprache") == "en" else BESCHREIBUNG).split("\n")[0]); done += 1
print("FERTIG", flush=True)
