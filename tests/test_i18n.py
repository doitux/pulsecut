"""Both languages are complete and placeholders match."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pulsecut import i18n

ROOT = Path(__file__).resolve().parent.parent


def test_all_texts_translated():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "i18n_keys.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_switch_language():
    old = i18n.get_lang()
    try:
        i18n.set_lang("en", persist=False)
        assert i18n.L("{n} Videos analysiert", n=3) == "3 videos analysed"
        assert i18n.fmt_day_time(datetime(2026, 7, 13, 14, 5)) == "Mon 13 Jul 14:05"
        i18n.set_lang("de", persist=False)
        assert i18n.L("{n} Videos analysiert", n=3) == "3 Videos analysiert"
        assert i18n.fmt_day_time(datetime(2026, 7, 13, 14, 5)) == "Mo 13.07. 14:05"
    finally:
        i18n.set_lang(old, persist=False)


def test_system_language(monkeypatch):
    for k in ("PULSECUT_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.system_lang() == "de"
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    assert i18n.system_lang() == "en"
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert i18n.system_lang() == "en"
