"""Whole workflow through the browser interface, once in German and once in English (simulated AI).

    python3 -m pytest tests/test_ui.py                 # needs: pip install playwright (+ a chromium)
    PULSECUT_SCREENSHOTS=docs/screenshots python3 -m pytest tests/test_ui.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import fake

pytestmark = [pytest.mark.ui, pytest.mark.slow]
playwright = pytest.importorskip("playwright.sync_api")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(und|oder|nicht|bitte|wird|werden|mit|der|die|das|eine?|Stück|Stücke|Schnitt|"
                    r"Schnitte|Szene|Szenen|Weiter|Zurück|Takte?|Musik|Fertig|Dauer|Länge|Ordner|ansehen)\b")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(params=["de", "en"])
def app(request, projekt, tmp_path):
    lang = request.param
    name = f"UI Test {lang}"
    proj = fake.RAW.parent / f"UI_Test_{lang}_Pulsecut"
    shutil.rmtree(proj, ignore_errors=True)
    proj.mkdir(parents=True)
    shutil.copytree(projekt.ordner / "cache", proj / "cache")   # reuse the analysis of the session project
    for f in (proj / "cache" / "emb").glob("*"):   # features of the simulated AI are produced again by the worker
        f.unlink()
    ana = proj / "cache" / "analyse.json"
    d = json.loads(ana.read_text())
    d["texte"], d["ton"] = {}, {}
    ana.write_text(json.dumps(d))
    env = dict(os.environ, PULSECUT_KI_PYTHON=sys.executable, PULSECUT_FAKE_WORKER=str(HERE / "fake_worker.py"),
               PULSECUT_LANG=lang, PYTHONPATH=str(ROOT))
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[k] = str(tmp_path / k.lower())
    port = free_port()
    log = open(tmp_path / "server.log", "w")
    p = subprocess.Popen([sys.executable, "-m", "pulsecut", "--nur-server", "--port", str(port)], cwd=ROOT, env=env,
                         stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    yield {"url": url, "lang": lang, "name": name, "proj": proj, "log": tmp_path / "server.log"}
    p.terminate()
    p.wait(10)
    log.close()


def test_workflow(app):
    from playwright.sync_api import sync_playwright
    lang = app["lang"]
    shots = os.environ.get("PULSECUT_SCREENSHOTS")
    texts, errors = {}, []
    with sync_playwright() as pw:
        exe = os.environ.get("PULSECUT_CHROMIUM")
        b = pw.chromium.launch(executable_path=exe or None,
                               args=["--autoplay-policy=no-user-gesture-required", "--use-fake-device-for-media-stream",
                                     "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": 1440, "height": 950}, permissions=["microphone"])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append("page: " + str(e)))
        pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)

        def snap(name):
            texts[name] = pg.inner_text("#rahmen")
            if shots:
                d = Path(shots) / lang
                d.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(d / f"{name}.png"))

        def zustand():
            return pg.evaluate("fetch('/api/zustand').then(r=>r.json())")

        def wait_job(name, timeout=600):
            t0 = time.time()
            pg.wait_for_timeout(500)
            while time.time() - t0 < timeout:
                j = zustand()["projekt"]["jobs"][name]
                if not j["laeuft"]:
                    return j
                pg.wait_for_timeout(500)
            raise AssertionError(f"job {name} did not finish")

        def ok_dialog():
            if pg.is_visible("#modal:not([hidden])"):
                pg.click("#modal .weiter .pri")
                pg.wait_for_timeout(500)

        # 1 project
        pg.goto(app["url"])
        pg.wait_for_selector("#pname")
        assert pg.get_attribute("html", "lang") == lang
        pg.fill("#pname", app["name"])
        pg.fill("#pvid", str(fake.RAW))
        pg.fill("#pmus", str(fake.MUSIK))
        snap("01_start")
        pg.click("#bneu")
        # 2 music
        pg.wait_for_selector("#mt2", timeout=180000)
        pg.wait_for_timeout(500)
        snap("02_musik")
        pg.click("#mt0 button[data-a=spaeter]")
        pg.wait_for_selector("#mt0 .fixed", timeout=60000)
        pg.click("#mt0 button[data-a=zuruecksetzen]")
        pg.wait_for_function("!document.querySelector('#mt0 .fixed')", timeout=60000)
        pg.click('#muebg [data-f=art] button[data-v=blende]')
        pg.wait_for_selector("#mbl")
        # 3 length
        pg.click("[data-go=laenge]")
        pg.wait_for_selector("#lwelle")
        pg.click('[data-f=mode] button[data-v=ziel]')
        pg.wait_for_selector("#lziel")
        pg.fill("#lziel", "3:00")
        pg.press("#lziel", "Enter")
        for i in range(3):   # shorten all three tracks at the end (each keeps at least 20 s)
            for _ in range(5):   # the box is redrawn after every answer – click again if a click got lost
                pg.wait_for_selector(f"[data-f=k_{i}]")
                pg.click(f'[data-f=k_{i}] button[data-v=hinten]')
                try:
                    pg.wait_for_selector(f'[data-f=k_{i}] button[data-v=hinten].on', timeout=5000)
                    break
                except Exception:
                    pass
        pg.wait_for_function("/(2:5[6-9]|3:0[0-4])/.test(document.querySelector('#lbox h3').innerText)", timeout=30000)
        snap("03_laenge")
        # 4 videos
        pg.click("[data-go=videos]")
        wait_job("analyse")
        pg.wait_for_selector("#vgrid .card")
        pg.wait_for_timeout(800)
        assert len(pg.query_selector_all("#vgrid .card")) == 38
        snap("04_videos")
        # 5 description: voice input (fake microphone + simulated speech model), then the full text
        pg.click("[data-go=ablauf]")
        pg.wait_for_selector("#btext")
        pg.click("#bmic")
        pg.wait_for_timeout(2000)
        pg.click("#bmic")
        pg.wait_for_function("document.querySelector('#btext').value.trim().length > 10", timeout=120000)
        first = fake.DESCRIPTION_EN if lang == "en" else fake.BESCHREIBUNG
        assert pg.input_value("#btext").strip() == first.split("\n")[0]
        pg.fill("#btext", first)
        pg.click("#bparse")
        pg.wait_for_timeout(500)
        ok_dialog()
        pg.wait_for_selector("#kwl .kw")
        n_kw = len(pg.query_selector_all("#kwl .kw"))
        assert n_kw == 10
        snap("05_ablauf")
        # 6 recognition with follow-up question
        pg.click("[data-go=erkennung]")
        pg.wait_for_selector("#bstart")
        pg.click("#bstart")
        j = wait_job("erkennung")
        assert not j["fehler"], j["fehler"]
        pg.wait_for_selector(".kwgruppe", timeout=30000)
        pg.wait_for_selector(".frage")
        frage = pg.inner_text(".frage b")
        assert ("Party / disco" if lang == "en" else "Party / Disco") in frage
        snap("06_erkennung")
        pg.click(".frage button[data-a=ja]")
        wait_job("erkennung")
        pg.wait_for_function(f"document.querySelectorAll('.kwgruppe').length === {n_kw + 1}", timeout=60000)
        # 7 weighting & order: group photo after the concert
        pg.click("[data-go=gewichtung]")
        pg.wait_for_selector(".gewicht")
        opts = pg.eval_on_selector_all("#bk1 option", "e=>e.map(x=>[x.value,x.innerText])")
        foto = next(v for v, n in opts if n in ("Gruppenfoto", "Group photo"))
        konzert = next(v for v, n in opts if n in ("Abschlusskonzert", "Final concert"))
        pg.select_option("#bk1", foto)
        pg.select_option("#bk2", konzert)
        pg.click("#bkgo")
        pg.wait_for_timeout(800)
        order = pg.eval_on_selector_all(".szrow", "e=>e.map(x=>x.querySelector('b').innerText)")
        names = dict(opts)
        last_concert = max(i for i, n in enumerate(order) if n == names[konzert])
        assert all(i > last_concert for i, n in enumerate(order) if n == names[foto])
        pg.click(".szrow .sztog")
        pg.wait_for_selector(".szclips")
        snap("07_gewichtung")
        # 8 cut settings
        pg.click("[data-go=schnitt]")
        pg.wait_for_selector("#splan")
        pg.click('[data-f=ueb] button[data-v=blende]')
        pg.wait_for_selector("#sbl")
        pg.fill("#sabs", "Thanks!" if lang == "en" else "Danke!")
        pg.dispatch_event("#sabs", "change")
        pg.wait_for_timeout(300)
        snap("08_schnitt")
        # 9 timeline: play, slip into a neighbour, give it up
        pg.click("#splan")
        pg.wait_for_selector("#tsh .shot", timeout=120000)
        pg.wait_for_timeout(1000)
        assert len(pg.query_selector_all("#tsh .shot")) > 20
        pg.click("#pplay")
        pg.wait_for_function("parseFloat(document.querySelector('#tph').style.left) > 0", timeout=90000)
        x1 = pg.eval_on_selector("#tph", "e=>parseFloat(e.style.left)")
        pg.wait_for_timeout(1200)
        x2 = pg.eval_on_selector("#tph", "e=>parseFloat(e.style.left)")
        assert x2 > x1, "playhead does not move"
        lit = pg.evaluate("()=>{const d=document.querySelector('#pcv').getContext('2d').getImageData(0,0,960,540).data;"
                          "let s=0;for(let i=0;i<d.length;i+=4000)s+=d[i]+d[i+1]+d[i+2];return s}")
        assert lit > 0, "preview stays black"
        pg.click("#pplay")
        tl = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        cnt = {}
        for s in tl["shots"]:
            cnt[s["clip"]] = cnt.get(s["clip"], 0) + 1
        sel = next(s for s in tl["shots"] if cnt[s["clip"]] >= 2)
        pg.evaluate("id=>document.querySelector(`.shot[data-id='${id}']`).scrollIntoView()", sel["id"])
        pg.click(f".shot[data-id='{sel['id']}']")
        pg.wait_for_selector("#fs .fenster")
        pg.wait_for_timeout(500)
        snap("09_timeline")
        fs = pg.query_selector("#fs").bounding_box()
        win = pg.query_selector("#fs .fenster").bounding_box()
        nb = pg.evaluate(f"fetch('/api/bereich?id={sel['id']}').then(r=>r.json())")
        other = nb["andere"][0]
        ox = fs["x"] + (other["src"] + 0.2) / sel["clipdauer"] * fs["width"]
        pg.mouse.move(win["x"] + win["width"] / 2, win["y"] + 30)
        pg.mouse.down()
        pg.mouse.move(ox + win["width"] / 2, win["y"] + 30, steps=12)
        assert pg.eval_on_selector("#fs .fenster", "e=>e.classList.contains('anschlag')")
        snap("10_anschlag")
        pg.mouse.up()
        pg.wait_for_selector("#modal:not([hidden])", timeout=5000)
        with pg.expect_response(lambda r: "/api/shot/slip" in r.url) as resp:
            pg.click("#modal .weiter .pri")
        assert resp.value.json()["ok"]
        pg.wait_for_timeout(1500)
        tl2 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        assert not [p for p in tl2["probleme"] if p["art"] in ("ueberlappung", "rand")]
        assert tl2["differenz"] == 0
        assert next(s for s in tl2["shots"] if s["id"] == sel["id"])["lock"]
        # length ×2 from the inspector
        pg.evaluate("id=>document.querySelector(`.shot[data-id='${id}']`).scrollIntoView()", sel["id"])
        pg.click(f".shot[data-id='{sel['id']}']")
        pg.wait_for_selector("#insp button[data-k]")
        pg.wait_for_timeout(500)
        pg.locator("#insp button[data-k]").nth(1).click()
        pg.wait_for_timeout(1500)
        ok_dialog()
        pg.wait_for_timeout(1000)
        tl3 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        assert tl3["differenz"] == 0
        assert not [p for p in tl3["probleme"] if p["art"] in ("ueberlappung", "rand")]
        # language switch round trip
        other_lang = "de" if lang == "en" else "en"
        pg.click(f"#lang button[data-v={other_lang}]")
        pg.wait_for_function(f"document.documentElement.lang === '{other_lang}'")
        pg.click(f"#lang button[data-v={lang}]")
        pg.wait_for_function(f"document.documentElement.lang === '{lang}'")
        pg.wait_for_selector("#tsh .shot")
        # 10 export
        pg.click("[data-go=export]")
        pg.wait_for_selector("#xgo")
        pg.click(".xf[value='1080p']")
        pg.click(".xf[value='720p']")
        pg.click("#xgo")
        j = wait_job("export", 1800)
        assert not j["fehler"], j["fehler"]
        pg.wait_for_selector("#xres .gut", timeout=30000)
        snap("11_export")
        files = zustand()["projekt"]["exporte"]
        assert any(f.endswith(".kdenlive") for f in files) and any(f.endswith("_720p.mp4") for f in files)
        b.close()
    assert not [e for e in errors if "favicon" not in e], errors
    if lang == "en":
        leftovers = {k: sorted(set(m.group(0) for m in GERMAN.finditer(v))) for k, v in texts.items()}
        leftovers = {k: v for k, v in leftovers.items() if v}
        assert not leftovers, json.dumps(leftovers, ensure_ascii=False)
