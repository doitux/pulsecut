#!/usr/bin/env python3
"""End-to-end smoke test of a built AppImage (only the Python standard library is needed).

    python3 tests/smoke_appimage.py dist/Pulsecut-1.0.0-x86_64.AppImage [--gui]

Generates a few tiny clips and a music track, starts the AppImage as a server, runs a whole project through the HTTP
interface (analysis, music, keywords, recognition without AI, plan, Kdenlive + 720p export) and checks the result.
With --gui it also opens the Qt window (needs a display, e.g. xvfb-run) and takes a screenshot.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


def make_media(root):
    vid, mus = root / "videos", root / "music"
    vid.mkdir(parents=True)
    mus.mkdir()
    for i, (src, t) in enumerate([("testsrc2", "10:00"), ("smptehdbars", "10:20"), ("rgbtestsrc", "11:40"),
                                  ("testsrc2=s=720x1280", "12:00"), ("smptebars", "12:30"), ("testsrc", "13:00")]):
        s = src if "=" in src else src + "=s=1280x720"
        ff("-f", "lavfi", "-i", f"{s}:r=30:d=20", "-f", "lavfi", "-i", "sine=f=440:d=20",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
           "-metadata", f"creation_time=2026-07-13T{t}:00Z", vid / f"VID_{i}.mp4")
    beat = "0.8*sin(2*PI*55*t)*exp(-25*mod(t,0.5))+0.2*sin(2*PI*440*t)*exp(-6*mod(t,0.5))"
    ff("-f", "lavfi", "-i", f"aevalsrc='{beat}|{beat}':s=44100:d=40", "-c:a", "libmp3lame", mus / "beat.mp3")
    return vid, mus


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    app = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix="pulsecut-smoke-"))
    env = dict(os.environ, APPIMAGE_EXTRACT_AND_RUN="1", PULSECUT_LANG="en")
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[k] = str(work / k.lower())
    out = subprocess.run([str(app), "--version"], env=env, capture_output=True, text=True, timeout=120)
    print("version:", out.stdout.strip(), out.stderr.strip()[-300:])
    assert out.returncode == 0 and "Pulsecut" in out.stdout

    vid, mus = make_media(work)
    port = free_port()
    log = open(work / "server.log", "w")
    p = subprocess.Popen([str(app), "--nur-server", "--port", str(port)], env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=60) as r:
            return json.loads(r.read())

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
        assert d.get("ok"), d
        return d

    def wait(*jobs, timeout=900):
        t0 = time.time()
        while time.time() - t0 < timeout:
            js = get("/api/zustand")["projekt"]["jobs"]
            if not any(js[j]["laeuft"] for j in jobs):
                for j in jobs:
                    assert not js[j]["fehler"], f"{j}: {js[j]['fehler']}"
                return js
            time.sleep(1)
        raise AssertionError(f"timeout waiting for {jobs}")

    try:
        for _ in range(120):
            try:
                z = get("/api/zustand")
                break
            except OSError:
                time.sleep(0.5)
        print("tools:", z["werkzeuge"], "| language:", z["sprache"])
        assert z["werkzeuge"]["ffmpeg"] and z["sprache"] == "en"
        assert b"const EN" in urllib.request.urlopen(base + "/static/i18n.js").read()
        post("/api/projekt/neu", {"name": "Smoke", "videos": str(vid), "musik": str(mus)})
        time.sleep(1)
        wait("analyse", "musik")
        v = get("/api/videos")
        assert len(v["clips"]) == 6, v
        m = get("/api/musik")
        print("music:", [(t["datei"], t["bpm"], t["takt"]) for t in m["stuecke"]])
        assert m["stuecke"] and abs(m["stuecke"][0]["bpm"] - 120) < 3
        kws = post("/api/ablauf", {"text": "First the arrival, then the games, finally the farewell."})["stichworte"]
        assert [k["name"] for k in kws] == ["Arrival", "Games", "Farewell"], kws
        post("/api/erkennung/start", {"mit_ki": False})
        time.sleep(1)
        wait("erkennung")
        tl = post("/api/plan", {"behalten": False})
        print("timeline:", len(tl["shots"]), "shots, problems", tl["probleme"], "difference", tl["differenz"])
        assert tl["shots"] and tl["differenz"] == 0
        assert not [x for x in tl["probleme"] if x["art"] in ("ueberlappung", "rand")]
        post("/api/export", {"kdenlive": True, "formate": ["720p"]})
        time.sleep(1)
        wait("export", timeout=1800)
        files = get("/api/zustand")["projekt"]["exporte"]
        print("exports:", files)
        mp4 = next(f for f in files if f.endswith(".mp4"))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                                   capture_output=True, text=True, check=True).stdout)
        assert abs(dur - tl["dauer"]) < 1.0, (dur, tl["dauer"])
        assert any(f.endswith(".kdenlive") for f in files)
    finally:
        p.terminate()
        p.wait(20)
        log.close()
        print((work / "server.log").read_text()[-3000:])

    if "--gui" in sys.argv:
        shot = work / "window.png"
        genv = dict(env, PULSECUT_SCREENSHOT=str(shot), PULSECUT_SCREENSHOT_MS="12000", PULSECUT_SOFTWARE_GL="1")
        r = subprocess.run([str(app)], env=genv, capture_output=True, text=True, timeout=180)
        print("gui:", r.returncode, r.stdout[-500:], r.stderr[-1500:])
        assert shot.exists() and shot.stat().st_size > 20000, "no screenshot of the window"
        target = os.environ.get("SMOKE_SCREENSHOT")
        if target:
            Path(target).write_bytes(shot.read_bytes())
    print("SMOKE TEST OK")


if __name__ == "__main__":
    main()
