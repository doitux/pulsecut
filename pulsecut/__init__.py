"""Pulsecut – Videos automatisch auf den Takt der Musik schneiden."""
VERSION = "1.0.0"
APP_NAME = "Pulsecut"
try:   # beim Bauen geschrieben: "nightly-<Build>-<Commit>" für Testversionen, leer für ein Release
    from ._build import BUILD
except ImportError:
    BUILD = ""


def version_text():
    """Was die Oberfläche und --version zeigen: „1.0.0“ oder „nightly 57 (ed90df8)“."""
    if BUILD.startswith("nightly-"):
        _, nr, commit = (BUILD.split("-") + ["", ""])[:3]
        return f"nightly {nr} ({commit})"
    return VERSION
