"""Two languages (German / English) for all texts the program shows. Modules import ``L as _t``.

German is the source language: texts in the code are German and are looked up in ``EN`` when the interface runs in
English. ``L("Text {x}", x=1)`` returns the text in the current language. Texts of the web interface live in
``ui/i18n.js`` and follow the same rule.
"""
import os
import threading

LANGS = ("de", "en")
_state = {"lang": None}
_lock = threading.Lock()


def system_lang():
    for k in ("PULSECUT_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = (os.environ.get(k) or "").strip().lower()
        if v and v not in ("c", "posix", "c.utf-8"):
            return "de" if v.startswith("de") else "en"
    return "en"


def _settings_file():
    from .util import CONFIG_HOME
    return CONFIG_HOME / "einstellungen.json"


def get_lang():
    if _state["lang"] is None:
        with _lock:
            if _state["lang"] is None:
                from .util import read_json
                forced = (os.environ.get("PULSECUT_LANG") or "").lower()[:2]
                saved = (read_json(_settings_file(), {}) or {}).get("sprache")
                _state["lang"] = forced if forced in LANGS else (saved if saved in LANGS else system_lang())
    return _state["lang"]


def set_lang(lang, persist=True):
    lang = lang if lang in LANGS else "en"
    _state["lang"] = lang
    if persist:
        from .util import CONFIG_HOME, atomic_write_json, read_json
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        d = read_json(_settings_file(), {}) or {}
        d["sprache"] = lang
        atomic_write_json(_settings_file(), d)
    return lang


def L(text, **kw):
    """Text in the current language; placeholders like {name} are filled from kw."""
    s = EN.get(text, text) if get_lang() == "en" else text
    return s.format(**kw) if kw else s


WOCHENTAG = {"de": "Mo Di Mi Do Fr Sa So".split(), "en": "Mon Tue Wed Thu Fri Sat Sun".split()}
MONAT_EN = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fmt_day_time(dt):
    """Weekday, date and time: 'Mo 13.07. 14:00' / 'Mon 13 Jul 14:00'."""
    lang = get_lang()
    wd = WOCHENTAG[lang][dt.weekday()]
    if lang == "en":
        return f"{wd} {dt.day} {MONAT_EN[dt.month - 1]} {dt:%H:%M}"
    return f"{wd} {dt:%d.%m. %H:%M}"


def fmt_datetime(dt):
    return f"{dt:%Y-%m-%d %H:%M:%S}" if get_lang() == "en" else f"{dt:%d.%m.%Y %H:%M:%S}"


EN = {
    # projekt.py
    "Kein Pulsecut-Projekt in {ordner}": "No Pulsecut project in {ordner}",
    "Videoordner nicht gefunden: {p}": "Video folder not found: {p}",
    "Musikordner nicht gefunden: {p}": "Music folder not found: {p}",
    "{name}: nicht lesbar ({err})": "{name}: cannot be read ({err})",
    "Videos werden eingelesen …": "Reading videos …",
    "Keine Videos im Videoordner gefunden.": "No videos found in the video folder.",
    "{name}: Analyse fehlgeschlagen ({err})": "{name}: analysis failed ({err})",
    "Analysiere Videos … {name} – noch ca. {eta} min": "Analysing videos … {name} – about {eta} min left",
    "Analysiere {n} Videos ({m} aus dem Zwischenspeicher) …": "Analysing {n} videos ({m} from cache) …",
    "{n} Videos analysiert": "{n} videos analysed",
    "Keine Musik im Musikordner gefunden (wav, mp3, flac, m4a, ogg …).":
        "No music found in the music folder (wav, mp3, flac, m4a, ogg …).",
    "Analysiere Musik: {name} …": "Analysing music: {name} …",
    "{n} Musikstücke analysiert": "{n} music tracks analysed",
    "Bereite Klick-Spur vor: {name} …": "Preparing click track: {name} …",
    "Videos warten, bis die Musik fertig analysiert ist …": "Videos wait until the music has been analysed …",
    "Die Videos sind noch nicht analysiert.": "The videos have not been analysed yet.",
    "Bitte zuerst den Ablauf beschreiben (Stichworte).": "Please describe the course of events first (keywords).",
    "KI schaut sich die Videos an … {a}/{b}": "AI is looking at the videos … {a}/{b}",
    "KI schaut sich die Videos an …": "AI is looking at the videos …",
    "KI hört sich den Ton an (Lachen, Applaus, Musik) …": "AI is listening to the sound (laughter, applause, music) …",
    "Vergleiche mit deinen Stichworten …": "Comparing with your keywords …",
    "Erkennung fertig": "Recognition finished",
    "Teil {n}": "Part {n}",
    "Bitte einen Namen angeben.": "Please enter a name.",
    "Die Musik ist noch nicht bereit.": "The music is not ready yet.",
    "Es gibt noch keine Szenen – bitte zuerst die Erkennung ausführen.":
        "There are no scenes yet – please run the recognition first.",
    "Schnitt nicht gefunden": "Shot not found",
    "Clip nicht gefunden": "Clip not found",
    "Der Clip ist für diese Länge zu kurz.": "The clip is too short for this length.",
    "In dieser Szene ist keine andere freie Stelle mehr.": "There is no other free passage left in this scene.",
    "Schreibe Kdenlive-Projekt …": "Writing Kdenlive project …",
    "Rendere {label} …": "Rendering {label} …",
    "Rendere {label} … {p} %": "Rendering {label} … {p} %",
    "melt: {e} – nehme ffmpeg (ohne Überblendungen)": "melt: {e} – using ffmpeg instead (no crossfades)",
    "Fertig: {files}": "Done: {files}",
    # server.py
    "Kein Projekt geöffnet": "No project open",
    "Nur beim Start als AppImage möglich.": "Only possible when started as an AppImage.",
    "Videos auf den Takt schneiden": "Cut videos to the beat",
    "Rückblick-Videos automatisch im Takt der Musik schneiden": "Automatically cut recap videos to the beat of the music",
    "Für die Spracheingabe bitte zuerst die KI-Erkennung einrichten (Schritt 6) – oder den Ablauf eintippen.":
        "For voice input, please set up AI recognition first (step 6) – or type the description.",
    "Text erkannt": "Text recognised",
    "unbekannt": "unknown",
    # planer.py
    "Clip {name} fehlt": "Clip {name} is missing",
    "{name}: Ausschnitt ragt über das Clip-Ende": "{name}: passage runs past the end of the clip",
    "{name}: zwei Ausschnitte überlappen sich": "{name}: two passages overlap",
    "Reihenfolge innerhalb der Szene nicht chronologisch": "Order within the scene is not chronological",
    "Zu wenig brauchbares Material, um die ganze Musik zu füllen.":
        "Not enough usable footage to fill the whole music.",
    # video.py
    "Schwenk nach rechts": "pan right",
    "Schwenk nach links": "pan left",
    "Neigung nach oben": "tilt up",
    "Neigung nach unten": "tilt down",
    "Zoom rein / ran": "zoom in",
    "Zoom raus / weg": "zoom out",
    "ruhig": "steady",
    "keine Videospur": "no video stream",
    "keine Bilder dekodiert": "no frames decoded",
    # export.py
    "Die Timeline ist leer.": "The timeline is empty.",
    "Sequenzen": "Sequences",
    "Videos": "Videos",
    "Musik": "Music",
    "Titel": "Titles",
    "Takt {n}": "Bar {n}",
    "Originalton": "Original sound",
    "Originalton 2": "Original sound 2",
    "Musik 2": "Music 2",
    "Hintergrund A": "Background A",
    "Hintergrund B": "Background B",
    "Szene": "Scene",
    "Automatisch erzeugt mit Pulsecut": "Created automatically with Pulsecut",
    "Full HD 1080p (MP4, H.264)": "Full HD 1080p (MP4, H.264)",
    "4K UHD (MP4, H.264)": "4K UHD (MP4, H.264)",
    "HD 720p (MP4, klein für Mail/Messenger)": "HD 720p (MP4, small for e-mail/messengers)",
    "Hochformat 9:16 (1080×1920, Reels/Status)": "Portrait 9:16 (1080×1920, reels/stories)",
    "Master-Qualität (MOV, ProRes 422 HQ)": "Master quality (MOV, ProRes 422 HQ)",
    "melt-Rendern fehlgeschlagen: ": "melt rendering failed: ",
    # musik.py
    "Audio zu kurz": "audio too short",
    "kein Rhythmus erkennbar": "no rhythm detected",
    # ki.py
    "Python-Umgebung konnte nicht angelegt werden": "Could not create the Python environment",
    "Python-Umgebung konnte nicht angelegt werden (sudo apt install python3-venv)":
        "Could not create the Python environment (sudo apt install python3-venv)",
    "PyTorch konnte nicht installiert werden (Internetverbindung?)": "Could not install PyTorch (internet connection?)",
    "KI-Pakete konnten nicht installiert werden": "Could not install the AI packages",
    "KI-Umgebung startet nicht: ": "AI environment does not start: ",
    "✔ KI-Erkennung eingerichtet": "✔ AI recognition set up",
    "KI-Erkennung ist nicht eingerichtet": "AI recognition is not set up",
    "lade KI-Modell {m} (beim ersten Mal Download)": "loading AI model {m} (downloaded the first time)",
    "KI-Worker abgebrochen: ": "AI worker stopped: ",
    "In diesem Clip ist keine freie Stelle mehr.": "There is no free passage left in this clip.",
    "In dieser Szene ist keine freie Stelle mehr.": "There is no free passage left in this scene.",
    "Kein Platz: Alle anderen Schnitte sind gesperrt.": "No room: all other shots are locked.",
    "Sprachmodell wird heruntergeladen (einmalig) …": "Downloading the speech model (one-time) …",
    "Sprachmodell wird geladen …": "Loading the speech model …",
    "Sprache wird erkannt …": "Recognising speech …",
    "Sprachmodell wird heruntergeladen (einmalig): {a} von ca. {b} MB":
        "Downloading the speech model (one-time): {a} of about {b} MB",
    "Sprache wird erkannt: {a} von {b} s": "Recognising speech: {a} of {b} s",
    "KI wird gestartet …": "Starting the AI …",
    # hwdec.py
    "VAAPI-Treiber fehlt (Paket intel-media-va-driver oder i965-va-driver)":
        "VAAPI driver missing (package intel-media-va-driver or i965-va-driver)",
    "vom Grafikchip nicht unterstützt": "not supported by the graphics chip",
    "Prozessor ist schneller": "processor is faster",
    "funktioniert nicht: {err}": "does not work: {err}",
    "10 Bit": "10-bit",
    "Grafikchip dekodiert {codec} ({x}× so schnell wie der Prozessor)":
        "graphics chip decodes {codec} ({x}× as fast as the processor)",
    "{codec}: Dekodierung auf dem Prozessor – {grund}": "{codec}: decoding on the processor – {grund}",
    "{name}: Grafikchip-Dekodierung gescheitert, nehme den Prozessor":
        "{name}: decoding on the graphics chip failed, using the processor",
    # util.py
    "Befehl fehlgeschlagen: {cmd} …": "Command failed: {cmd} …",
    # app.py
    "Ordner wählen": "Choose folder",
    "Projektordner öffnen": "open a project folder",
    "statt eigenem Fenster den normalen Browser verwenden": "use the normal web browser instead of an own window",
    "Port des lokalen Servers (Standard: frei wählen)": "port of the local server (default: any free port)",
    "nur den Server starten (für Tests)": "start only the server (for tests)",
    "Sprache der Oberfläche": "interface language",
    "Projekt konnte nicht geöffnet werden:": "Could not open project:",
    "Qt (PySide6) nicht gefunden – öffne den Browser.": "Qt (PySide6) not found – opening the web browser.",
    "Zum Beenden Strg+C drücken.": "Press Ctrl+C to quit.",
}
