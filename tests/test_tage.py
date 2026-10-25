"""Projects over several days: detecting the days, keywords per day, recognition per day."""
import numpy as np

import fake
from conftest import prepare
from pulsecut import erkennung as ER

TAGE4 = [{"datum": d} for d in ("2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16")]


def test_days_detected(projekt):
    info = projekt.tage_info()
    assert info["eindeutig"], info
    assert [t["datum"] for t in info["tage"]] == ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]
    assert sum(t["n"] for t in info["tage"]) == info["n"]
    assert info["quelle"]["beide"] > 0 and info["quelle"]["beide_gleich"] == info["quelle"]["beide"]
    assert info["tage"][0]["kurz"] == "Mo" and info["tage"][0]["label"].startswith("Mo 13.07.")


def test_not_offered_when_unsure():
    class C:
        def __init__(self, day, src, name_day=None):
            from datetime import datetime
            self.start = datetime(2026, 7, day, 12)
            self.time_source = src
            self.name_start = datetime(2026, 7, name_day, 12) if name_day else None
    one = [C(13, "Metadaten") for _ in range(10)]
    assert ER.tage_erkennen(one)["grund"] == "ein_tag"
    copied = [C(13 + i % 3, "Dateidatum") for i in range(12)]          # only file dates (copied files)
    assert ER.tage_erkennen(copied)["grund"] == "unsicher"
    clash = [C(13 + i % 3, "Metadaten", 20) for i in range(12)]         # metadata and file name disagree
    assert ER.tage_erkennen(clash)["grund"] == "widerspruch"
    stray = [C(13, "Metadaten") for _ in range(30)] + [C(25, "Metadaten")]   # one video with a wrong clock
    assert ER.tage_erkennen(stray)["grund"] == "zu_wenig"
    late = C(14, "Metadaten")
    late.start = late.start.replace(hour=1)                              # 1 am belongs to the day before
    assert ER.tag_von(late.start).isoformat() == "2026-07-13"


def test_split_description_by_days():
    t = ("Am Anfang kommen alle mit dem Bus an, dann Anmeldung. Jeden Tag Proben in Registern. Am zweiten Tag Fußball. "
         "Am Mittwoch Ausflug ins Museum. Am letzten Tag Abschlusskonzert, danach Gruppenfoto.")
    r = ER.nach_tagen_teilen(t, TAGE4)
    assert r["erkannt"]
    assert "Bus" in r["tage"][0] and "Fußball" in r["tage"][1] and "Museum" in r["tage"][2]
    assert "Abschlusskonzert" in r["tage"][3] and "Proben" in r["alle"]
    en = ER.nach_tagen_teilen("First the bus arrives. Every day rehearsals. On the next day football. "
                              "On Wednesday the museum. On the last day the final concert.", TAGE4)
    assert "bus" in en["tage"][0] and "football" in en["tage"][1] and "museum" in en["tage"][2]
    assert "concert" in en["tage"][3] and "rehearsals" in en["alle"]
    kws = ER.parse_tage(r["tage"], r["alle"], TAGE4, "de")
    proben = [k for k in kws if k["basis"].startswith("Proben")]
    assert [k["tag"] for k in proben] == [t["datum"] for t in TAGE4] and all(k["wiederkehrend"] for k in proben)
    assert len({k["id"] for k in kws}) == len(kws)
    assert ER.kw_text(proben[0]) == ER.kw_text(proben[3])                # same picture search on every day


def test_recognition_per_day(projekt):
    """Rehearsals on every day look alike – with keywords per day each clip lands on its own day's keyword."""
    prepare(projekt)
    info = projekt.tage_info()
    lab = fake.labels()
    daten = [t["datum"] for t in info["tage"]]
    kinds = sorted({fake.true_kw(lab[c.name]) for c in projekt.clips})
    kws = []
    for d in daten:
        for kind in kinds:
            if any(fake.true_kw(lab[c.name]) == kind and ER.tag_von(c.start).isoformat() == d for c in projekt.clips):
                kws.append({"id": f"k{len(kws) + 1}", "name": f"Art{kind}", "text": "", "tag": d,
                            "wiederkehrend": True, "gewicht": 1.0})
    projekt.set_stichworte(kws)
    kws = projekt.d["stichworte"]
    assert all(" · " in k["name"] and k["basis"].startswith("Art") for k in kws)
    # simulated AI: one text feature per kind (the same on every day), clips look like their kind
    rng = np.random.default_rng(5)
    V = {kind: rng.normal(size=512).astype(np.float32) for kind in kinds}
    for v in V.values():
        v /= np.linalg.norm(v)
    for k in kws:
        projekt.cache["texte"][ER.kw_text(k)] = V[int(k["basis"][3:])].tolist()
    for t in ER.voc_texts():
        projekt.cache["texte"][t] = (rng.normal(size=512) / 23).tolist()
    for c in projekt.clips:
        n = len(c.ana["ki_frames"])
        E = V[fake.true_kw(lab[c.name])][None, :] * 0.32 + rng.normal(size=(n, 512)).astype(np.float32) * 0.03
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        np.save(projekt.dirs["emb"] / f"{c.hash}.npy", E.astype(np.float16))
    tag = {k["id"]: k["tag"] for k in kws}

    def richtiger_tag():
        projekt.compute_erkennung()
        act = [c for c in projekt.clips if c.prio != "raus" and c.kw]
        return sum(tag[c.kw] == ER.tag_von(c.start).isoformat() for c in act) / len(act)

    projekt.tage_setzen(False)
    ohne = richtiger_tag()
    projekt.tage_setzen(True)
    mit = richtiger_tag()
    print(f"right day: without days {ohne:.0%}, with days {mit:.0%}")
    assert mit == 1.0 and mit > ohne
    projekt.tage_setzen(False)
