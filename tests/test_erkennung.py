"""Keywords from German and English descriptions, language detection, recognition without AI."""
from fake import BESCHREIBUNG, DESCRIPTION_EN
from pulsecut import erkennung as ER


def names(text, **kw):
    return [k["name"] for k in ER.parse_beschreibung(text, **kw)]


def test_german_keywords():
    kws = ER.parse_beschreibung(BESCHREIBUNG)
    assert [k["name"] for k in kws] == ["Bus Jugendherberge", "Anmeldung Anwesenheitsliste", "Kennenlernabend Spielen",
                                         "Proben Registern", "Freizeit Fußball", "Ausflug Museum",
                                         "Registerproben Dirigentinnen", "Abschlusskonzert", "Gruppenfoto", "Abreise Bus"]
    rec = {k["name"]: k["wiederkehrend"] for k in kws}
    assert rec["Proben Registern"] and rec["Freizeit Fußball"] and not rec["Gruppenfoto"]


def test_english_keywords():
    kws = ER.parse_beschreibung(DESCRIPTION_EN)
    n = [k["name"] for k in kws]
    assert n[0] == "Bus" and "Registration" in n and "Free time" in n and "Final concert" in n
    assert n[-2:] == ["Group photo", "Departure"]
    rec = {k["name"]: k["wiederkehrend"] for k in kws}
    assert rec["Free time"] and not rec["Group photo"]


def test_language_detection():
    assert ER.sprache_des_textes(BESCHREIBUNG) == "de"
    assert ER.sprache_des_textes(DESCRIPTION_EN) == "en"
    assert ER.sprache_des_textes("Gruppenfoto", default="en") == "en"


def test_repeated_items_merge():
    kws = ER.parse_beschreibung("Morning: rehearsal. Then lunch. Then rehearsal.", sprache="en")
    assert [k["name"] for k in kws] == ["Rehearsal", "Lunch"]
    assert kws[0]["wiederkehrend"]


def test_vocabulary_is_bilingual():
    ids = [v[0] for v in ER.VOKABULAR]
    assert len(ids) == len(set(ids))
    assert ER.voc_label(0, "en") == "Party / disco" and ER.voc_label(0, "de") == "Party / Disco"
    assert all(len(v) == 4 and v[3] for v in ER.VOKABULAR)


def test_assignment_without_ai(projekt):
    kws = ER.parse_beschreibung(BESCHREIBUNG)
    path, conf = ER.zuordnen(projekt.clips, [None] * len(projekt.clips), kws)
    assert path == sorted(path) and path[0] == 0 and path[-1] == len(kws) - 1


def test_no_keywords_from_fillers_or_days():
    """„da haben wir“ or „am ersten Tag“ alone are not keywords; day phrases only sort, they are not part of a name."""
    n = names("Am ersten Tag. Da haben wir. Dann Anreise mit dem Bus. Am zweiten Tag Freizeit mit Fußball. "
              "Am Mittwoch Ausflug ins Museum. Am 16.07. das Konzert. Jeden Tag Proben.")
    assert n == ["Anreise Bus", "Freizeit Fußball", "Ausflug Museum", "Konzert", "Proben"]
    e = names("On the first day we arrived. Then there was. Then registration. On the next day football. "
              "On Wednesday the museum. Every day rehearsals.")
    assert e == ["Registration", "Football", "Museum", "Rehearsals"]
    kws = ER.parse_beschreibung("Am zweiten Tag Freizeit mit Fußball. Jeden Tag Proben.")
    assert kws[0]["text"] == "Freizeit mit Fußball" and kws[1]["wiederkehrend"]
