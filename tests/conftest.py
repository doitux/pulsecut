"""Shared test setup: isolated config/data folders, synthetic media, one analysed project for the whole session."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# never touch the real ~/.config/pulsecut etc. of whoever runs the tests – except for the AI tests, which want to
# reuse an installed AI environment and the downloaded models (PULSECUT_TEST_REAL_HOME=1)
if not os.environ.get("PULSECUT_TEST_REAL_HOME"):
    # Playwright finds its browsers via XDG_CACHE_HOME – keep pointing at the real one
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"))
    _home = Path(tempfile.mkdtemp(prefix="pulsecut-test-home-"))
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        os.environ[k] = str(_home / k.lower())
os.environ.setdefault("PULSECUT_LANG", "de")

import fake  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: browser tests with Playwright (need chromium)")
    config.addinivalue_line("markers", "slow: long-running tests")
    config.addinivalue_line("markers", "ki: tests with the real AI models (need the AI environment)")


@pytest.fixture(scope="session")
def media():
    fake.ensure_media()
    return fake


@pytest.fixture(scope="session")
def projekt(media):
    from pulsecut.projekt import Job, Projekt
    pr = Projekt.erstellen("Camp 2026", fake.RAW, fake.MUSIK, fake.PROJ)
    a, m = Job("analyse"), Job("musik")
    pr.analyse_job(a)
    pr.musik_job(m)
    assert pr.clips and pr.tracks
    return pr


def prepare(pr, beschreibung=None, ziel=None, **schnitt):
    """Keywords from the description, simulated AI, recognition and a fresh plan.
    ziel = film length in seconds (all tracks shortened at the end), None = all of the music."""
    from pulsecut import erkennung as ER
    pr.d["ziel_dauer"] = ziel
    pr.d["kuerzen"] = {t["datei"]: "hinten" for t in pr.tracks} if ziel else {}
    pr.d["clips"] = {}
    pr.d["abgelehnt"] = []
    pr.d["szenen"] = {}
    pr.d["szenen_folge"] = None
    pr.d["schnitt"].update({"k": 0, "raster": "takt", "uebergang": "hart", "blende": 0.5, "bewegung": False,
                            "originalton": "auto"})
    pr.d["schnitt"].update(schnitt)
    pr.apply_user_clip_settings()
    with pr.lock:
        pr.update_layout()
    pr.set_stichworte(ER.parse_beschreibung(beschreibung or fake.BESCHREIBUNG))
    lab = fake.fake_ki(pr)
    pr.compute_erkennung()
    pr.d["timeline"] = None
    pr.plan(keep_locked=False)
    return lab


def pytest_runtest_logreport(report):
    """On GitHub Actions: failures become annotations (readable via the API without downloading logs)."""
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    text = str(report.longrepr)
    lines = [ln for ln in text.splitlines() if ln.startswith("E ") or "Error" in ln][-25:] or text.splitlines()[-25:]
    msg = "\n".join(lines)[-3500:]
    for a, b in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A")):
        msg = msg.replace(a, b)
    title = f"{report.nodeid} ({report.when})"
    for a, b in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A"), (":", "%3A"), (",", "%2C")):
        title = title.replace(a, b)
    sys.__stdout__.write(f"::error title={title}::{msg}\n")
    sys.__stdout__.flush()
