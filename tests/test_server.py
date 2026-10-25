"""Local HTTP interface: static files, state, language switch, project opening."""
import json
import urllib.request

import pytest

from pulsecut import server
from pulsecut.i18n import get_lang, set_lang


@pytest.fixture(scope="module")
def url():
    srv, u = server.start_server(0)
    yield u
    srv.shutdown()


def get(u, path):
    with urllib.request.urlopen(u + path.lstrip("/"), timeout=30) as r:
        return r.read()


def post(u, path, body):
    req = urllib.request.Request(u + path.lstrip("/"), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def test_static(url):
    html = get(url, "/").decode()
    assert "/static/i18n.js" in html and "/static/app.js" in html
    assert b"const EN" in get(url, "/static/i18n.js")
    assert get(url, "/static/qwebchannel.js")


def test_state_and_language(url):
    z = json.loads(get(url, "/api/zustand"))
    assert z["ok"] and z["sprache"] in ("de", "en") and z["app"] == "Pulsecut"
    old = get_lang()
    try:
        assert post(url, "/api/sprache/oberflaeche", {"sprache": "en"})["sprache"] == "en"
        assert json.loads(get(url, "/api/zustand"))["sprache"] == "en"
        r = post(url, "/api/stichworte", {"liste": []})
        assert not r["ok"] and r["fehler"] == "No project open"
    finally:
        set_lang(old, persist=False)


def test_open_project(url, projekt):
    import time
    r = post(url, "/api/projekt/oeffnen", {"ordner": str(projekt.ordner)})
    assert r["ok"]
    for _ in range(600):   # analysis comes from the cache, this takes seconds
        jobs = json.loads(get(url, "/api/zustand"))["projekt"]["jobs"]
        if not jobs["analyse"]["laeuft"] and not jobs["musik"]["laeuft"]:
            break
        time.sleep(0.5)
    assert not jobs["analyse"]["fehler"] and not jobs["musik"]["fehler"]
    r = post(url, "/api/ablauf", {"text": "First the arrival, then the concert, finally the group photo."})
    assert [k["name"] for k in r["stichworte"]] == ["Arrival", "Concert", "Group photo"]
    v = json.loads(get(url, "/api/videos"))
    assert len(v["clips"]) == 38


def test_recent_projects_only_existing(tmp_path, monkeypatch):
    """Projects whose folder is gone are no longer listed under „recently opened“."""
    import json
    from pulsecut import projekt as P
    monkeypatch.setattr(P, "CONFIG_HOME", tmp_path / "cfg")
    da = tmp_path / "Da_Pulsecut"
    da.mkdir()
    (da / P.PROJEKT_DATEI).write_text("{}")
    weg = tmp_path / "Weg_Pulsecut"
    leer = tmp_path / "Leer_Pulsecut"          # folder still there, but no project in it any more
    leer.mkdir()
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "zuletzt.json").write_text(json.dumps(
        [{"ordner": str(p), "name": p.name} for p in (da, weg, leer)]))
    assert [x["name"] for x in P.recent_projects()] == ["Da_Pulsecut"]
    assert len(P.recent_projects(alle=True)) == 3
