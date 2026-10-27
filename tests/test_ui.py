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

        def waehle(css, value):
            """Picks an entry like a person: click on the own selection list next to the <select>, then on the entry."""
            i = pg.eval_on_selector(css, "(s,v)=>[...s.options].findIndex(o=>o.value===v)", value)
            assert i >= 0, (css, value)
            pg.click(f"{css} + .auswahl")
            pg.wait_for_selector(".awliste")
            pg.click(f".awliste button[data-i='{i}']")
            assert not pg.query_selector(".awliste")

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
        cards = pg.query_selector_all("#vgrid .card")
        assert len(cards) == 38
        excluded = pg.eval_on_selector("#vgrid .card:nth-child(14) .meta b", "e=>e.innerText").split(". ", 1)[1]
        pg.click("#vgrid .card:nth-child(14) [data-f=prio] button[data-v=raus]")   # this clip must not come back
        pg.wait_for_timeout(800)
        snap("04_videos")
        # 5 description: voice input (fake microphone + simulated speech model), then the full text
        pg.click("[data-go=ablauf]")
        pg.wait_for_selector("#btext")
        # several recording days: the question comes up; try "by days", then go on with everything together
        pg.wait_for_selector("#tja")
        assert len(pg.query_selector_all(".tagliste li")) == 4
        pg.click("#tja")
        pg.wait_for_selector(".tagtext")
        assert len(pg.query_selector_all(".tagtext")) == 4
        pg.fill("#btext", "Bus und Anmeldung. Jeden Tag Proben. Am letzten Tag das Abschlusskonzert." if lang == "de" else
                "Bus and registration. Every day rehearsals. On the last day the final concert.")
        pg.click("#tverteil")
        pg.wait_for_function("document.querySelectorAll('.tagtext')[3].value.length > 5")
        assert "Bus" in pg.input_value(".tagtext >> nth=0") and pg.input_value("#talle")
        snap("05a_tage")
        pg.click('[data-f="tmod"] button[data-v="0"]')
        pg.wait_for_function("!document.querySelector('.tagtext')")
        pg.click("#bmic")
        pg.wait_for_timeout(2000)
        pg.click("#bmic")
        pg.wait_for_selector("#sjob .fortschritt", timeout=20000)        # progress of the voice input is shown
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
        er = pg.evaluate("fetch('/api/erkennung').then(r=>r.json())")["erkennung"]
        assert er["ausgeschlossen"] == 1
        assert all(c["name"] != excluded for z in er["szenen"] for c in z["clipliste"]), "clip set to Out came back"
        # move the first scene into a new keyword
        new_name = "Test category" if lang == "en" else "Testkategorie"
        # no selection list sticks out of its scene card
        assert pg.evaluate("""[...document.querySelectorAll('.szk')].every(k => { const a = k.querySelector('.auswahl');
            return a && a.getBoundingClientRect().right <= k.getBoundingClientRect().right + 0.5; })""")
        first = pg.eval_on_selector(".szk", "e=>e.dataset.id")
        waehle(f'.szk[data-id="{first}"] .zkw', "__neu__")
        pg.wait_for_selector("#mein")
        pg.fill("#mein", new_name)
        pg.click("#modal .weiter .pri")
        pg.wait_for_function(f"document.querySelectorAll('.kwgruppe').length === {n_kw + 2}", timeout=60000)
        heads = pg.eval_on_selector_all(".kwgruppe .kopf b", "e=>e.map(x=>x.innerText)")
        assert new_name in heads
        n_groups = n_kw + 2
        # open a scene, play one clip and move just that clip to another keyword (the scene is split)
        er = pg.evaluate("fetch('/api/erkennung').then(r=>r.json())")
        z = next(z for z in er["erkennung"]["szenen"] if z["n"] >= 2)
        clip, rest = z["clipliste"][-1]["name"], [c["name"] for c in z["clipliste"][:-1]]
        ziel = next(k for k in er["stichworte"] if k["id"] != z["kw"])
        pg.click(f'.szk[data-id="{z["id"]}"] .strip')
        pg.wait_for_selector("#mbox.breit .ezclip")
        assert pg.eval_on_selector_all("#mbox .ezclip", "e=>e.map(x=>x.dataset.c)") == rest + [clip]
        pg.click(f'#mbox .ezclip[data-c="{clip}"] .strip')
        pg.wait_for_selector(f'#mbox .ezclip[data-c="{clip}"] video')
        snap("06_szene_clips")
        pg.click(f'#mbox .ezclip[data-c="{clip}"] .ezkw + .auswahl'); pg.wait_for_selector(".awliste")
        snap("06_szene_liste")
        pg.keyboard.press("Escape")
        # pressing and releasing the mouse on the list only opens it – nothing is picked by the release, and the list
        # never lies on top of the field (that is what went wrong with the system selection under Linux)
        knopf = f'#mbox .ezclip[data-c="{clip}"] .ezkw + .auswahl'
        bb = pg.locator(knopf).bounding_box()
        vorher = pg.eval_on_selector(f'#mbox .ezclip[data-c="{clip}"] .ezkw', "s=>s.value")
        for hoehe in (950, 560):   # also when there is little room below and the list opens upwards
            pg.set_viewport_size({"width": 1440, "height": hoehe})
            pg.wait_for_timeout(200)
            bb = pg.locator(knopf).bounding_box()
            pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(150)
            pg.mouse.up()
            pg.wait_for_selector(".awliste")
            lb = pg.locator(".awliste").bounding_box()
            assert lb["y"] >= bb["y"] + bb["height"] or lb["y"] + lb["height"] <= bb["y"], (bb, lb)
            pg.wait_for_timeout(300)
            assert pg.query_selector(".awliste")
            assert pg.eval_on_selector(f'#mbox .ezclip[data-c="{clip}"] .ezkw', "s=>s.value") == vorher
            pg.keyboard.press("Escape")
            assert not pg.query_selector(".awliste") and not pg.locator("#modal").is_hidden()
        pg.set_viewport_size({"width": 1440, "height": 950})
        waehle(f'#mbox .ezclip[data-c="{clip}"] .ezkw', ziel["id"])
        pg.wait_for_function(f"!document.querySelector('#mbox .ezclip[data-c=\"{clip}\"]')", timeout=30000)
        assert pg.eval_on_selector_all("#mbox .ezclip", "e=>e.map(x=>x.dataset.c)") == rest   # rest of the scene stays open
        kw_von = lambda: {c["name"]: (c["kw"], c["kw_manuell"]) for s in pg.evaluate(
            "fetch('/api/erkennung').then(r=>r.json())")["erkennung"]["szenen"] for c in s["clipliste"]}
        assert kw_von()[clip] == (ziel["id"], ziel["id"])
        assert all(kw_von()[n][0] == z["kw"] for n in rest)
        pg.click("#modal .weiter .pri")
        # get it back with "⇆ get clips here" on the old keyword
        pg.click(f'.kwgruppe[data-kw="{z["kw"]}"] .holen')
        pg.wait_for_selector("#ezholliste")
        if not pg.query_selector(f'#ezholliste .ezclip[data-c="{clip}"]'):
            pg.check("#ezalle")
        assert pg.is_disabled("#modal .weiter .pri")
        pg.check(f'#ezholliste .ezclip[data-c="{clip}"] .ezhaken')
        assert pg.inner_text("#modal .weiter .pri").endswith("(1)")
        pg.click("#modal .weiter .pri")
        pg.wait_for_function(f"fetch('/api/erkennung').then(r=>r.json()).then(e=>e.erkennung.szenen.some(s=>s.clipliste.some(c=>c.name==='{clip}'&&c.kw==='{z['kw']}')))", timeout=30000)
        pg.wait_for_selector("#toast.on")
        # and back to automatic via the selection in the scene view
        sid = next(s["id"] for s in pg.evaluate("fetch('/api/erkennung').then(r=>r.json())")["erkennung"]["szenen"]
                   if any(c["name"] == clip for c in s["clipliste"]))
        pg.click(f'.szk[data-id="{sid}"] .strip')
        pg.wait_for_selector(f'#mbox .ezclip[data-c="{clip}"]')
        waehle(f'#mbox .ezclip[data-c="{clip}"] .ezkw', "__auto__")
        pg.wait_for_function(f"fetch('/api/erkennung').then(r=>r.json()).then(e=>e.erkennung.szenen.some(s=>s.clipliste.some(c=>c.name==='{clip}'&&!c.kw_manuell)))", timeout=30000)
        assert kw_von()[clip] == (z["kw"], "")
        pg.click("#modal .weiter .pri")
        assert pg.evaluate("document.querySelectorAll('.kwgruppe').length") == n_groups
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
        order = pg.eval_on_selector_all(".szrow", "e=>e.map(x=>x.querySelector('.zkw').selectedOptions[0].innerText)")
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
        pg.wait_for_selector(".stilk[data-s=karte] img")   # title library: pick the "card" style
        pg.click(".stilk[data-s=karte]")
        pg.wait_for_selector(".stilk.on[data-s=karte]")
        assert pg.evaluate("fetch('/api/titelstile').then(r=>r.json())")["aktuell"]["stil"] == "karte"
        # font picker (each font shown in itself) and font sizes
        pg.click("#sfont")
        pg.wait_for_selector(".schriftliste .schrift")
        n_fonts = len(pg.query_selector_all(".schriftliste .schrift"))
        if n_fonts > 1:
            fam = pg.get_attribute(".schriftliste .schrift:nth-of-type(2)", "data-f") or \
                pg.eval_on_selector_all(".schriftliste .schrift", "e=>e[1].dataset.f")
            with pg.expect_response(lambda r: "/api/schnitt" in r.url):
                pg.eval_on_selector_all(".schriftliste .schrift", "e=>e[1].click()")
            pg.wait_for_timeout(500)
            assert pg.evaluate("fetch('/api/titelstile').then(r=>r.json())")["aktuell"]["schrift"] == fam
        else:
            pg.click("#modal [data-x=abbr]")
        pg.eval_on_selector("#sgr", "e=>{e.value=140;e.dispatchEvent(new Event('change'))}")
        pg.eval_on_selector("#sgru", "e=>{e.value=80;e.dispatchEvent(new Event('change'))}")
        pg.wait_for_timeout(800)
        akt = pg.evaluate("fetch('/api/titelstile').then(r=>r.json())")["aktuell"]
        assert akt["groesse"] == 140 and akt["groesse_unter"] == 80 and akt["fett"] is True
        with pg.expect_response(lambda r: "/api/schnitt" in r.url):
            pg.click("#sfett")
        pg.wait_for_timeout(300)
        assert pg.evaluate("fetch('/api/titelstile').then(r=>r.json())")["aktuell"]["fett"] is False
        pg.fill("#sabs", "Thanks!" if lang == "en" else "Danke!")
        pg.dispatch_event("#sabs", "change")
        pg.wait_for_timeout(300)
        snap("08_schnitt")
        # 9 timeline: play, slip into a neighbour, give it up
        pg.click("#splan")
        pg.wait_for_selector("#tsh .shot", timeout=120000)
        pg.wait_for_timeout(1000)
        assert len(pg.query_selector_all("#tsh .shot")) > 20
        big = pg.eval_on_selector("#pcv", "e=>e.getBoundingClientRect().width")
        pg.click("#pgr button[data-v=klein]")                  # smaller preview, more room below
        pg.wait_for_timeout(300)
        assert pg.eval_on_selector("#pcv", "e=>e.getBoundingClientRect().width") < big * 0.6
        pg.click("#pgr button[data-v=gross]")
        pg.wait_for_timeout(300)
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
        # original sound per shot (step 9): off for one shot, then the switch for the whole film
        pg.click(f".shot[data-id='{sel['id']}']")
        pg.wait_for_selector("#insp [data-f=iton]")
        pg.wait_for_timeout(300)
        with pg.expect_response(lambda r: "/api/shot/ton" in r.url):
            pg.click("#insp [data-f=iton] button[data-v=aus]")
        pg.wait_for_timeout(1200)
        tl4 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        s4 = next(s for s in tl4["shots"] if s["id"] == sel["id"])
        assert s4["ton"] == "aus" and s4["atmo"] is None and s4["ton_info"]["grund"] == "aus_schnitt"
        assert pg.inner_text("#itoninfo")
        with pg.expect_response(lambda r: "/api/schnitt" in r.url):
            pg.click("#tton button[data-v=aus]")
        pg.wait_for_timeout(1200)
        tl5 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        assert tl5["originalton"] == "aus" and not any(s["atmo"] for s in tl5["shots"])
        with pg.expect_response(lambda r: "/api/schnitt" in r.url):
            pg.click("#tton button[data-v=leiser]")
        pg.wait_for_timeout(1200)
        assert pg.evaluate("fetch('/api/timeline').then(r=>r.json())")["originalton"] == "auto"
        # insert another clip of the same scene right after a shot
        tlx = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        anchor = None
        for s_ in tlx["shots"]:
            sc = pg.evaluate(f"fetch('/api/szenenclips?id={s_['id']}').then(r=>r.json())")
            if any(c["frei"] for c in sc["clips"]):
                anchor = s_
                break
        assert anchor, "no scene with free material in the test footage"
        pg.evaluate("id=>document.querySelector(`.shot[data-id='${id}']`).scrollIntoView()", anchor["id"])
        pg.click(f".shot[data-id='{anchor['id']}']")
        pg.wait_for_selector("#iplus")
        pg.wait_for_timeout(300)
        pg.click("#iplus")
        pg.wait_for_selector(".clipwahl button")
        snap("11_clip_einfuegen")
        with pg.expect_response(lambda r: "/api/shot/einfuegen" in r.url) as resp:
            pg.click(".clipwahl button:not([disabled])")
        r_ = resp.value.json()
        assert r_["ok"], r_
        pg.wait_for_timeout(1500)
        tl6 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        ids6 = [s_["id"] for s_ in tl6["shots"]]
        assert ids6.index(r_["id"]) == ids6.index(anchor["id"]) + 1
        assert tl6["differenz"] == 0 and not [p for p in tl6["probleme"] if p["art"] in ("ueberlappung", "rand")]
        # remove with the Del key: choice dialog, the shots behind move up, everything before is finished
        tl7 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        victim = tl7["shots"][len(tl7["shots"]) // 2]
        nxt = tl7["shots"][len(tl7["shots"]) // 2 + 1]
        pg.evaluate("id=>document.querySelector(`.shot[data-id='${id}']`).scrollIntoView()", victim["id"])
        pg.click(f".shot[data-id='{victim['id']}']")
        pg.wait_for_selector("#iweg")
        pg.wait_for_timeout(300)
        pg.keyboard.press("Delete")
        pg.wait_for_selector(".entfwahl button")
        snap("12_entfernen")
        with pg.expect_response(lambda r: "/api/shot/entfernen" in r.url) as resp:
            pg.click(".entfwahl button[data-v=nachbar]")
        assert resp.value.json()["ok"]
        pg.wait_for_timeout(1500)
        tl8 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        ids8 = [s_["id"] for s_ in tl8["shots"]]
        assert victim["id"] not in ids8 and ids8[len(tl7["shots"]) // 2] == nxt["id"]
        assert tl8["fertig_bis"] == tl7["shots"][len(tl7["shots"]) // 2 - 1]["id"]
        assert tl8["differenz"] == 0 and not [p for p in tl8["probleme"] if p["art"] in ("ueberlappung", "rand")]
        pg.wait_for_selector("#tfix:not(.leer)")
        assert pg.is_visible(f".shot.fertig[data-id='{ids8[0]}']")
        # undo (button) brings the removed shot back exactly, redo (Ctrl+Y) removes it again, Ctrl+Z undoes again
        with pg.expect_response(lambda r: "/api/verlauf/zurueck" in r.url):
            pg.click("#tundo")
        pg.wait_for_selector(f".shot[data-id='{victim['id']}']")
        tl_u = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        assert [s_["id"] for s_ in tl_u["shots"]] == [s_["id"] for s_ in tl7["shots"]]
        assert tl_u["verlauf"]["vor"] and not pg.is_disabled("#tredo")
        pg.click("#tsh")                                   # focus on the timeline, not on an input
        with pg.expect_response(lambda r: "/api/verlauf/vor" in r.url):
            pg.keyboard.press("Control+y")
        pg.wait_for_function(f"!document.querySelector(\".shot[data-id='{victim['id']}']\")")
        with pg.expect_response(lambda r: "/api/verlauf/zurueck" in r.url):
            pg.keyboard.press("Control+z")
        pg.wait_for_selector(f".shot[data-id='{victim['id']}']")
        pg.click("#tverl")
        pg.wait_for_selector("#mbox .vz")
        snap("13_verlauf")
        with pg.expect_response(lambda r: "/api/verlauf/vor" in r.url):
            pg.click("#mbox .vz.vor")                       # redo from the list
        pg.wait_for_function(f"!document.querySelector(\".shot[data-id='{victim['id']}']\")")
        pg.wait_for_timeout(500)
        # film shorter, then undo
        pg.keyboard.press("Delete")
        pg.wait_for_selector(".entfwahl button[data-v=kuerzer]")
        with pg.expect_response(lambda r: "/api/shot/entfernen" in r.url):
            pg.click(".entfwahl button[data-v=kuerzer]")
        pg.wait_for_selector("#endezur")
        with pg.expect_response(lambda r: "/api/ende/zuruecknehmen" in r.url):
            pg.click("#endezur")
        pg.wait_for_timeout(1200)
        tl9 = pg.evaluate("fetch('/api/timeline').then(r=>r.json())")
        assert tl9["ende_weg"] == 0 and tl9["differenz"] == 0
        # playback across cuts into other video files: no still-image fallback once it runs
        pg.evaluate("""() => { const P = PLY; P._fb = 0; const o = P.img.bind(P);
            P.img = u => { if (u && !u.includes('titel') && P.playing && P.t > 1.2) P._fb++; return o(u); }; }""")
        pg.evaluate("PLY.seek(0); PLY.play()")
        pg.wait_for_timeout(9000)
        fb = pg.evaluate("PLY._fb")
        pg.evaluate("PLY.pause()")
        assert fb <= 3, f"preview showed the still image {fb} times while playing"
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
