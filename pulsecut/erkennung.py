"""Erkennung: Stichworte aus der Ablaufbeschreibung, Zuordnung der Clips zu Stichworten (Bildinhalt + Ablauf),
Szenen bilden, unklare Szenen und vermutlich vergessene Stichworte finden."""
import re

import numpy as np

STOP = {"am", "an", "dann", "danach", "zuerst", "es", "wir", "die", "der", "das", "den", "dem", "des", "ein", "eine",
        "einen", "einem", "einer", "und", "zum", "zur", "im", "in", "auf", "mit", "bei", "nach", "vor", "alle", "viele",
        "ganz", "anfang", "ende", "schluss", "abschluss", "später", "anschließend", "als", "nächstes", "zuletzt",
        "außerdem", "hier", "da", "dort", "sie", "er", "ich", "man", "kommt", "kommen", "gibt", "gab", "gab's",
        "gibt's", "war", "waren", "ist", "sind", "wird", "werden", "haben", "hatten", "hat", "noch", "auch", "sehr",
        "immer", "wieder", "jeden", "jede", "jeder", "tag", "tage", "morgen", "abend", "mittag", "zwischendurch",
        "erst", "erste", "ersten", "letzte", "letzten", "letzter", "zwei", "drei", "dabei", "dazu", "wo", "wie", "was",
        "unsere", "unser", "unseren", "dieser", "diese", "dieses", "so", "also", "na", "ja", "äh", "ähm", "halt",
        "einfach", "mal", "gleich", "kurz", "lang", "danach", "darauf", "worauf", "dabei", "uns", "sich",
        "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", "wochenende", "nachmittag",
        "vormittag", "nachts", "abends", "morgens", "mittags"}
CONNECT = r"\b(?:und\s+dann|dann|danach|anschließend|anschliessend|später|zum\s+schluss|zum\s+abschluss|am\s+ende|" \
          r"als\s+nächstes|als\s+naechstes|zuletzt|und\s+zuletzt|außerdem|ausserdem)\b"
WIEDER = ("immer wieder", "jeden tag", "täglich", "zwischendurch", "mehrmals", "jeden morgen", "jeden abend",
          "regelmäßig", "an allen tagen", "die ganze zeit", "jeden mittag", "mehrere male")

# Englische Ablaufbeschreibungen: Füllwörter, Verben und Zeitangaben, die kein Stichwort sind
STOP_EN = {"a", "an", "the", "and", "or", "then", "after", "afterwards", "that", "this", "these", "those", "first",
           "firstly", "next", "later", "finally", "lastly", "at", "in", "on", "of", "to", "into", "onto", "for", "from",
           "with", "by", "we", "us", "our", "they", "them", "their", "he", "she", "it", "its", "i", "you", "everyone",
           "everybody", "all", "some", "many", "lots", "lot", "there", "here", "was", "were", "is", "are", "be", "been",
           "being", "has", "have", "had", "having", "do", "did", "does", "doing", "get", "gets", "got", "go", "goes",
           "went", "gone", "going", "come", "comes", "came", "coming", "arrive", "arrives", "arrived", "arriving",
           "leave", "leaves", "left", "leaving", "make", "makes", "made", "take", "takes", "took", "taken", "play",
           "plays", "played", "playing", "start", "starts", "started", "end", "ends", "ended", "begin", "begins",
           "began", "beginning", "end", "ending", "day", "days", "daily", "every", "each", "morning", "mornings",
           "evening", "evenings", "afternoon", "night", "nights", "noon", "week", "weekend", "monday", "tuesday",
           "wednesday", "thursday", "friday", "saturday", "sunday", "today", "yesterday", "between", "meanwhile",
           "again", "also", "too", "very", "just", "so", "well", "um", "uh", "like", "really", "always", "sometimes",
           "often", "last", "final", "second", "two", "three", "one", "where", "when", "what", "which", "who", "how",
           "while", "during", "before", "about", "around", "up", "down", "out", "over", "off", "back"}
CONNECT_EN = r"\b(?:and\s+then|then|after\s+that|afterwards|after\s+this|later\s+on|later|next|finally|lastly|" \
             r"at\s+the\s+end|in\s+the\s+end|to\s+finish|followed\s+by|after\s+which)\b"
WIEDER_EN = ("every day", "each day", "daily", "in between", "again and again", "several times", "every morning",
             "every evening", "regularly", "all the time", "repeatedly", "each morning", "each evening", "every night",
             "throughout", "on all days", "now and then")
# Wörter, die in englischen Beschreibungen trotzdem zum Namen gehören dürfen ("free time", "final concert")
KEEP_EN = {"free", "final", "last"}

_DE_HINT = {"und", "der", "die", "das", "dann", "danach", "mit", "ein", "eine", "ist", "sind", "wir", "am", "im", "zum",
            "auf", "nach", "den", "dem", "es", "gibt", "jeden", "zwischendurch"}
_EN_HINT = {"and", "the", "then", "with", "a", "is", "are", "we", "at", "in", "on", "to", "of", "there", "after",
            "every", "first", "finally", "between"}


def sprache_des_textes(text, default="de"):
    """Grobe Erkennung, ob eine Beschreibung deutsch oder englisch ist (zählt typische Funktionswörter)."""
    w = re.findall(r"[a-zäöüß]+", (text or "").lower())
    de = sum(x in _DE_HINT for x in w)
    en = sum(x in _EN_HINT for x in w)
    if de == en:
        return default
    return "de" if de > en else "en"


# Häufige Programmpunkte für die Rückfrage „War da nicht noch …?“: (id, Name de, Name en, Beschreibung für CLIP).
# Die Beschreibung ist englisch, weil CLIP mit englischen Texten am besten funktioniert.
VOKABULAR = [
    ("party", "Party / Disco", "Party / disco", "a party or disco with colourful lights, music and dancing"),
    ("lagerfeuer", "Lagerfeuer", "Campfire", "people sitting around a campfire in the evening"),
    ("grillen", "Grillen", "Barbecue", "a barbecue outdoors, sausages on the grill"),
    ("essen", "Essen", "Meals", "people eating together at tables in a dining hall"),
    ("fruehstueck", "Frühstück", "Breakfast", "breakfast in the morning with bread rolls and tea"),
    ("spieleabend", "Spieleabend", "Games night", "board games and card games at a table"),
    ("sport", "Fußball / Sport", "Football / sports", "playing football or sports on a lawn"),
    ("schwimmen", "Schwimmen", "Swimming", "children swimming in a pool or a lake"),
    ("strand", "Strand", "Beach", "at the beach with sand and sea"),
    ("wanderung", "Wanderung", "Hiking", "a hike through forest and nature"),
    ("bus", "Busfahrt", "Bus ride", "a coach trip, people sitting in a bus"),
    ("ankunft", "Ankunft", "Arrival", "arriving with suitcases and luggage in front of a house"),
    ("abschied", "Abreise / Abschied", "Departure / farewell", "saying goodbye, people waving farewell"),
    ("gruppenfoto", "Gruppenfoto", "Group photo", "many people lining up for a group photo"),
    ("konzert", "Konzert / Auftritt", "Concert / performance", "a concert or performance on a stage in front of an audience"),
    ("probe", "Probe / Musizieren", "Rehearsal / making music", "musicians rehearsing with instruments and sheet music"),
    ("theater", "Theater / Vorführung", "Theatre / show", "a theatre play or show on a stage"),
    ("tanzen", "Tanzen", "Dancing", "people dancing together"),
    ("museum", "Museum / Ausstellung", "Museum / exhibition", "visiting a museum or an exhibition"),
    ("stadt", "Stadtbesichtigung", "City tour", "sightseeing in a city with buildings and streets"),
    ("basteln", "Basteln / Workshop", "Crafts / workshop", "crafts, painting or a workshop at tables"),
    ("geburtstag", "Geburtstag / Torte", "Birthday / cake", "a birthday with a cake and candles"),
    ("siegerehrung", "Siegerehrung", "Award ceremony", "an award ceremony with prizes, certificates or trophies"),
    ("rede", "Rede / Ansprache", "Speech", "a person giving a speech in front of a group"),
    ("boot", "Bootsfahrt", "Boat trip", "a trip on a boat or ship on the water"),
    ("zoo", "Zoo / Tiere", "Zoo / animals", "animals in a zoo or on a farm"),
    ("freizeitpark", "Freizeitpark", "Theme park", "rides in a theme park"),
    ("schnee", "Schnee / Rodeln", "Snow / sledging", "snow, sledging and a snowball fight"),
    ("feuerwerk", "Feuerwerk", "Fireworks", "fireworks in the night sky"),
    ("zimmer", "Zimmer / Schlafsaal", "Rooms / dormitory", "a room with beds in a hostel"),
    ("kuchen", "Kaffee und Kuchen", "Coffee and cake", "coffee and cake in the afternoon"),
    ("spiele", "Spiele draußen", "Outdoor games", "group games outside on a lawn"),
    ("hochzeit", "Hochzeit", "Wedding", "a wedding with bride and groom"),
    ("kochen", "Kochen", "Cooking", "cooking together in a kitchen"),
    ("radtour", "Radtour", "Bike tour", "a bike tour with several bicycles"),
]


def voc_texts():
    return [v[3] for v in VOKABULAR]


def voc_label(j, lang="de"):
    return VOKABULAR[j][2] if lang == "en" else VOKABULAR[j][1]


def _name_de(p):
    words = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]*", p)
    caps = [w for w in words if w[0].isupper() and w.lower() not in STOP]
    return caps[:2] or [w for w in words if w.lower() not in STOP][:3] or words[:2]


def _name_en(p):
    """Erster Inhaltsbegriff, mit einem direkt folgenden zweiten Wort ("youth hostel", "group photo")."""
    words = re.findall(r"[A-Za-z][A-Za-z\-']*", p)
    content = [i for i, w in enumerate(words) if w.lower() not in STOP_EN or w.lower() in KEEP_EN]
    content = [i for i in content if not (words[i].lower() in KEEP_EN and i + 1 not in content)]
    if not content:
        return words[:2]
    i = content[0]
    out = [words[i]]
    if i + 1 in content:
        out.append(words[i + 1])
    out = [w.lower() for w in out]
    out[0] = out[0][:1].upper() + out[0][1:]
    return out


def parse_beschreibung(text, start_id=1, sprache=None):
    """Freie Ablaufbeschreibung (deutsch oder englisch) → Liste von Stichworten (Name, Beschreibung, wiederkehrend)."""
    t = re.sub(r"\s+", " ", (text or "").replace("\r", "\n")).strip()
    if not t:
        return []
    lang = sprache or sprache_des_textes(t)
    connect = CONNECT_EN if lang == "en" else CONNECT
    split_extra = r"|(?=\bin between\b)|(?=\bagain and again\b)|(?=\bmeanwhile\b)" if lang == "en" else \
        r"|(?=\bzwischendurch\b)|(?=\bimmer wieder\b)"
    trail = r"(\s+(and|or|as well as|,))+\s*$" if lang == "en" else r"(\s+(und|oder|sowie|,))+\s*$"
    wieder = WIEDER_EN if lang == "en" else WIEDER
    parts = []
    for line in re.split(r"[\n]|(?<=[.!?;])\s+|\s+[-–•]\s+|^\s*[-–•]\s*", text):
        line = (line or "").strip()
        if not line:
            continue
        for p in re.split(connect + split_extra, line, flags=re.I):
            p = re.sub(trail, "", (p or "").strip(" ,.;:!?-–•\t"), flags=re.I)
            p = re.sub(r"^\d+[.)]\s*", "", p)
            if len(p) >= 3:
                parts.append(p)
    out, seen = [], {}
    for p in parts:
        name_words = _name_en(p) if lang == "en" else _name_de(p)
        if not name_words:
            continue
        name = " ".join(name_words)[:32]
        low = p.lower()
        rec = any(x in low for x in wieder)
        key = name.lower()
        if key in seen:   # doppelter Programmpunkt: Beschreibung ergänzen, als wiederkehrend markieren
            k = seen[key]
            k["text"] += "; " + p
            k["wiederkehrend"] = True
            continue
        k = {"id": f"k{start_id + len(out)}", "name": name, "text": p, "wiederkehrend": rec, "gewicht": 1.0}
        seen[key] = k
        out.append(k)
    return out


def kw_text(k):
    """Text, den die KI mit den Bildern vergleicht (ohne Tagesangabe: „Proben · Di“ → „Proben“)."""
    name = k.get("basis") or k["name"]
    return f"{name}: {k['text']}" if k.get("text") and k["text"] != name else name


def clip_sims(E, T):
    """Ähnlichkeit eines Clips (Bilder E: n×d) zu Texten T (k×d): Mittel der besseren Hälfte der Bilder."""
    if E is None or not len(E) or not len(T):
        return None
    S = E.astype(np.float32) @ T.T
    n = len(S)
    top = max(1, int(np.ceil(n * 0.5)))
    return np.sort(S, axis=0)[-top:].mean(axis=0)


def _logsumexp(a, axis=None):
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    return np.squeeze(out, axis=axis) if axis is not None else float(np.ravel(out)[0])


def zuordnen(clips, sims, stichworte, manuell=None):
    """Clips (in Reihenfolge) den Stichworten zuordnen: Bildinhalt (sims: Liste je Clip, None ohne KI) kombiniert mit
    dem beschriebenen Ablauf (Stichwort-Reihenfolge, Zeitabstände). Gibt (Zuordnung, Sicherheit) zurück."""
    n, K = len(clips), len(stichworte)
    manuell = manuell or {}
    if n == 0 or K == 0:
        return [None] * n, [0.0] * n
    have_ki = any(s is not None for s in sims)
    if not have_ki:
        return _ohne_ki(clips, stichworte, manuell)
    rec = np.array([bool(k.get("wiederkehrend")) for k in stichworte])
    E = np.zeros((n, K))
    for i, s in enumerate(sims):
        if s is not None:
            z = 100.0 * np.asarray(s, np.float64)
            E[i] = z - _logsumexp(z)
        m = manuell.get(i)
        if m is not None:
            E[i] = -1e9
            E[i, m] = 0.0
    ks = np.arange(K)

    def trans(i):
        gap = abs((clips[i].start - clips[i - 1].end).total_seconds()) / 60.0
        base = 1.6 if gap < 3 else (0.9 if gap < 30 else 0.35)
        d = ks[None, :] - ks[:, None]            # [alt, neu]
        A = np.where(d == 0, 0.0, base + 0.35 * np.maximum(0, np.abs(d) - 1))
        back = d < 0
        A = A + np.where(back, np.where(rec[None, :], 0.8, 2.8), 0.0)
        return -A

    start = -0.5 * ks
    V = start + E[0]
    back_ptr = np.zeros((n, K), int)
    TR = [None] + [trans(i) for i in range(1, n)]
    for i in range(1, n):
        cand = V[:, None] + TR[i]
        back_ptr[i] = np.argmax(cand, axis=0)
        V = cand.max(axis=0) + E[i]
    path = [int(np.argmax(V))]
    for i in range(n - 1, 0, -1):
        path.append(int(back_ptr[i, path[-1]]))
    path = path[::-1]
    # Vorwärts-Rückwärts für die Sicherheit
    F = np.zeros((n, K))
    F[0] = start + E[0]
    for i in range(1, n):
        F[i] = _logsumexp(F[i - 1][:, None] + TR[i], axis=0) + E[i]
    B = np.zeros((n, K))
    for i in range(n - 2, -1, -1):
        B[i] = _logsumexp(TR[i + 1] + (E[i + 1] + B[i + 1])[None, :], axis=1)
    P = F + B
    P = np.exp(P - _logsumexp(P, axis=1)[:, None])
    conf = [float(P[i, path[i]]) for i in range(n)]
    return path, conf


def _ohne_ki(clips, stichworte, manuell):
    """Ohne Bilderkennung: Ablauf an den größten Zeitlücken in so viele Teile teilen, wie es Stichworte gibt."""
    n, K = len(clips), len(stichworte)
    gaps = [(abs((clips[i].start - clips[i - 1].end).total_seconds()), i) for i in range(1, n)]
    cuts = sorted(i for _, i in sorted(gaps, reverse=True)[:max(0, K - 1)])
    path, k, ci = [], 0, 0
    for i in range(n):
        while ci < len(cuts) and i >= cuts[ci]:
            k = min(K - 1, k + 1)
            ci += 1
        path.append(manuell.get(i, k))
    return path, [1.0 if i in manuell else 0.3 for i in range(n)]


def szenen_bilden(clips, path, conf, stichworte, max_gap_min=25):
    """Aufeinanderfolgende Clips desselben Stichworts mit höchstens max_gap_min Pause = eine Szene."""
    scenes, cur = [], []
    for i, c in enumerate(clips):
        if cur:
            p = cur[-1]
            gap = (c.start - clips[p].end).total_seconds() / 60.0
            if path[i] != path[p] or gap > max_gap_min:
                scenes.append(cur)
                cur = []
        cur.append(i)
    if cur:
        scenes.append(cur)
    out = []
    for idxs in scenes:
        k = path[idxs[0]]
        kw = stichworte[k] if k is not None and k < len(stichworte) else None
        cs = [clips[i] for i in idxs]
        out.append({"id": f"{kw['id'] if kw else 'x'}|{cs[0].name}", "kw": kw["id"] if kw else None,
                    "clips": cs, "start": cs[0].start, "end": max(c.end for c in cs),
                    "sicherheit": float(np.mean([conf[i] for i in idxs]))})
    return out


def rueckfragen(scenes, clip_sim_kw, clip_sim_voc, kw_emb, voc_emb, stichworte, abgelehnt, kw_index, lang="de"):
    """Vermutlich vergessene Programmpunkte: Szenen, die zu einem Vokabular-Eintrag deutlich besser passen als zu
    ihrem Stichwort – und dieser Eintrag ähnelt keinem vorhandenen Stichwort."""
    if voc_emb is None or not len(voc_emb) or not scenes:
        return []
    near = (voc_emb @ kw_emb.T).max(axis=1) if len(kw_emb) else np.zeros(len(voc_emb))
    votes = {}
    for z in scenes:
        sv = [clip_sim_voc.get(c.key) for c in z["clips"] if clip_sim_voc.get(c.key) is not None]
        sk = [clip_sim_kw.get(c.key) for c in z["clips"] if clip_sim_kw.get(c.key) is not None]
        if not sv or not sk or z["kw"] is None:
            continue
        sv, sk = np.mean(sv, axis=0), np.mean(sk, axis=0)
        own = float(sk[kw_index[z["kw"]]])
        j = int(np.argmax(sv))
        diff = float(sv[j]) - own
        if VOKABULAR[j][0] in abgelehnt or VOKABULAR[j][1] in abgelehnt or near[j] > 0.82:
            continue
        if diff > 0.012:
            dur = sum(c.dur for c in z["clips"])
            v = votes.setdefault(j, {"szenen": [], "diff": 0.0, "sek": 0.0})
            v["szenen"].append(z["id"])
            v["diff"] = max(v["diff"], diff)
            v["sek"] += dur
    out = []
    for j, v in votes.items():
        if v["diff"] > 0.03 or len(v["szenen"]) >= 2:
            out.append({"id": VOKABULAR[j][0], "label": voc_label(j, lang), "text": VOKABULAR[j][3], "szenen": v["szenen"],
                        "staerke": round(v["diff"], 3), "sekunden": round(v["sek"], 1)})
    out.sort(key=lambda x: (-len(x["szenen"]), -x["staerke"]))
    return out[:3]


# ═════════════════════════════════════════════ Mehrere Tage
# Bei Freizeiten, Klassenfahrten oder Urlauben über mehrere Tage gibt es oft an jedem Tag ähnliche Szenen (Proben,
# Busfahrten). Mit Stichworten je Tag sucht die Erkennung die Proben vom ersten Tag nur in den Videos vom ersten Tag.

TAG_GRENZE_STUNDE = 4    # was bis 4 Uhr morgens aufgenommen wurde, gehört noch zum Vortag (Party, Nachtwanderung)
SICHERE_QUELLEN = ("Handy-Metadaten", "Metadaten", "Dateiname")
TAEGLICH = ("jeden tag", "täglich", "an allen tagen", "jeden morgen", "jeden abend", "jeden mittag", "every day",
            "each day", "daily", "every morning", "every evening", "each morning", "each evening", "every night",
            "on all days", "on every day")


def tag_von(dt):
    from datetime import timedelta
    return (dt - timedelta(hours=TAG_GRENZE_STUNDE)).date()


def tage_erkennen(clips, max_tage=10):
    """Über wie viele Tage geht das Material – und ist das sicher? Aufnahmezeit aus den Metadaten und aus dem Dateinamen
    werden gegeneinander geprüft. Videos, deren Zeit nur vom Dateidatum stammt (z. B. kopiert), zählen als unsicher."""
    from collections import Counter
    clips = [c for c in clips if c.start is not None]
    n = len(clips)
    tage = Counter(tag_von(c.start) for c in clips)
    sicher = [c for c in clips if c.time_source in SICHERE_QUELLEN]
    beide = [c for c in clips if c.time_source != "Dateiname" and c.time_source in SICHERE_QUELLEN and c.name_start]
    gleich = [c for c in beide if tag_von(c.name_start) == tag_von(c.start)]
    quelle = {"metadaten": sum(1 for c in clips if c.time_source in ("Handy-Metadaten", "Metadaten")),
              "dateiname": sum(1 for c in clips if c.name_start is not None), "beide": len(beide),
              "beide_gleich": len(gleich), "unsicher": n - len(sicher)}
    liste = []
    for d in sorted(tage):
        cs = [c for c in clips if tag_von(c.start) == d]
        liste.append({"datum": d.isoformat(), "n": len(cs), "von": min(c.start for c in cs).strftime("%H:%M"),
                      "bis": max(c.start for c in cs).strftime("%H:%M")})
    grund = ""
    if len(tage) < 2:
        grund = "ein_tag"
    elif len(tage) > max_tage:
        grund = "zu_viele"
    elif len(sicher) < 0.8 * n:
        grund = "unsicher"
    elif beide and len(gleich) < 0.9 * len(beide):
        grund = "widerspruch"
    elif min(tage.values()) < max(2, int(0.03 * n)):
        grund = "zu_wenig"     # ein „Tag“ mit nur einem Video ist eher ein Ausreißer (falsch gestellte Uhr)
    return {"eindeutig": not grund, "grund": grund, "tage": liste, "quelle": quelle, "n": n}


_ORD_DE = {"erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fünft": 5, "fuenft": 5, "sechst": 6, "siebt": 7,
           "acht": 8, "neunt": 9, "zehnt": 10}
_ORD_EN = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
           "ninth": 9, "tenth": 10}
_ZAHL_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_WT_DE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
_WT_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _tag_marken(text, tage):
    """Stellen im Text, an denen ein Tag beginnt: [(Position, Tag-Index oder "+1")]."""
    from datetime import date
    days = [date.fromisoformat(t["datum"]) for t in tage]
    N = len(days)
    out = []
    low = text.lower()
    pats = [
        (r"\b(?:am\s+|an\s+dem\s+)?(" + "|".join(_ORD_DE) + r")(?:e|en|er|es)\s+tag\b", lambda m: _ORD_DE[m.group(1)] - 1),
        (r"\b(?:on\s+)?(?:the\s+)?(" + "|".join(_ORD_EN) + r")\s+day\b", lambda m: _ORD_EN[m.group(1)] - 1),
        (r"\btag\s+(\d{1,2})\b", lambda m: int(m.group(1)) - 1),
        (r"\bday\s+(\d{1,2}|" + "|".join(_ZAHL_EN) + r")\b",
         lambda m: (int(m.group(1)) if m.group(1).isdigit() else _ZAHL_EN[m.group(1)]) - 1),
        (r"\b(?:am\s+)?letzten\s+tag\b|\babreisetag\b|\b(?:on\s+)?the\s+last\s+day\b|\bdeparture\s+day\b",
         lambda m: N - 1),
        (r"\banreisetag\b|\b(?:am\s+)?ankunftstag\b|\barrival\s+day\b", lambda m: 0),
        (r"\b(?:am\s+)?(?:nächsten|naechsten|folgenden)\s+tag\b|\btags\s+darauf\b|\bam\s+tag\s+danach\b|"
         r"\b(?:on\s+)?the\s+(?:next|following)\s+day\b|\bthe\s+day\s+after\b", lambda m: "+1"),
        (r"\b(?:am\s+|on\s+)?(" + "|".join(_WT_DE + _WT_EN) + r")s?\b",
         lambda m: next((i for i, d in enumerate(days) if d.weekday() == ((_WT_DE + _WT_EN).index(m.group(1)) % 7)),
                        None)),
        (r"\b(?:am\s+)?(\d{1,2})\.\s?(\d{1,2})\.", lambda m: next((i for i, d in enumerate(days)
                                                                   if (d.day, d.month) == (int(m.group(1)),
                                                                                           int(m.group(2)))), None)),
    ]
    for pat, fn in pats:
        for m in re.finditer(pat, low):
            if any(low[max(0, m.start() - 8):m.start()].endswith(x) for x in ("jeden ", "every ", "each ", "pro ")):
                continue
            v = fn(m)
            if v is None or (v != "+1" and not 0 <= v < N):
                continue
            out.append((m.start(), m.end(), v))
    out.sort()
    res = []
    for pos, end, v in out:   # überlappende Treffer (z. B. „am letzten Tag“ und „Tag“) nur einmal
        if res and pos < res[-1][1]:
            continue
        res.append((pos, end, v))
    return res


def nach_tagen_teilen(text, tage):
    """Eine Ablaufbeschreibung über mehrere Tage auf die Tage verteilen: {"tage": [Text je Tag], "alle": Text für
    Programmpunkte an allen Tagen, "erkannt": ob Tage im Text genannt wurden}. Sätze mit „jeden Tag“, „täglich“ …
    kommen zu „alle“. Text vor der ersten Tagesangabe gehört zum ersten Tag."""
    N = len(tage)
    res = {"tage": [""] * N, "alle": "", "erkannt": False}
    t = (text or "").strip()
    if not t or N == 0:
        return res
    marken = _tag_marken(t, tage)
    res["erkannt"] = bool(marken)
    grenzen = [(0, 0, 0)] + marken
    cur = 0
    stuecke = []
    for j, (pos, end, v) in enumerate(grenzen):
        cur = (min(N - 1, cur + 1) if v == "+1" else v) if j else 0
        ende = grenzen[j + 1][0] if j + 1 < len(grenzen) else len(t)
        stuecke.append((cur, t[end:ende].lstrip(" ,:–-")))   # die Tagesangabe selbst gehört nicht zum Ablauf
    for tag, st in stuecke:
        for satz in re.split(r"(?<=[.!?;])\s+|\n+", st):
            satz = satz.strip()
            if not satz:
                continue
            ziel = "alle" if any(x in satz.lower() for x in TAEGLICH) else tag
            if ziel == "alle":
                res["alle"] = (res["alle"] + " " + satz).strip()
            else:
                res["tage"][ziel] = (res["tage"][ziel] + " " + satz).strip()
    return res


def tag_label(datum, lang="de", kurz=True, alle_tage=None):
    """„Di“ (alle Tage in einer Woche) bzw. „14.07.“ – für Stichwort-Namen wie „Proben · Di“."""
    from datetime import date
    from .i18n import WOCHENTAG
    d = date.fromisoformat(datum)
    eine_woche = alle_tage is None or len({date.fromisoformat(x).weekday() for x in alle_tage}) == len(alle_tage)
    wt = WOCHENTAG["en" if lang == "en" else "de"][d.weekday()]
    if kurz and eine_woche:
        return wt
    return f"{wt} {d.day}/{d.month}" if lang == "en" else f"{wt} {d:%d.%m.}"


def parse_tage(texte, alle, tage, lang=None, start_id=1):
    """Stichworte je Tag: [Text je Tag], Text für alle Tage → Stichworte mit "tag" (Datum) und "basis" (Name ohne Tag).
    Programmpunkte „an allen Tagen“ bekommt jeder Tag als eigenes, wiederkehrendes Stichwort."""
    daten = [t["datum"] for t in tage]
    alle_kw = parse_beschreibung(alle, sprache=lang) if (alle or "").strip() else []
    out = []
    for i, d in enumerate(daten):
        eigene = parse_beschreibung(texte[i] if i < len(texte) else "", sprache=lang)
        namen = {k["name"].lower() for k in eigene}
        extra = [dict(k, wiederkehrend=True) for k in alle_kw if k["name"].lower() not in namen]
        for k in eigene + extra:
            lab = tag_label(d, lang or "de", alle_tage=daten)
            out.append({"id": f"k{start_id + len(out)}", "name": f"{k['name']} · {lab}"[:40], "basis": k["name"],
                        "text": k["text"], "wiederkehrend": bool(k["wiederkehrend"]), "gewicht": 1.0, "tag": d})
    return out
