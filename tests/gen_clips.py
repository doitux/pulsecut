#!/usr/bin/env python3
"""Synthetic test footage: an invented week-long music camp with 38 phone clips (categories, changes of view,
types of sound, GPS, one clip without metadata) and three synthetic music tracks.

    python3 tests/gen_clips.py OUT_CLIPS OUT_MUSIC

Everything is generated with ffmpeg test sources – no real people or recordings."""
import os
import subprocess
import sys
from datetime import datetime, timedelta

FONT = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")
             if os.path.exists(f)), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
JH = (54.1000, 12.1000)       # hostel (invented)
MUSEUM = (54.1500, 12.2500)   # museum (invented)
MS = (53.9000, 12.0000)       # departure point (invented)

# Bildquellen (günstig zu erzeugen); jede "Sicht" sieht klar anders aus
def src(kind, dur, arg=0):
    if kind == "bars":
        return f"testsrc2=s=1280x720:r=30:d={dur},hue=h={arg}"
    if kind == "smpte":
        return f"smptehdbars=s=1280x720:r=30:d={dur},hue=h={arg}"
    if kind == "life":
        return (f"life=s=320x180:r=30:mold=10:ratio=0.5:death_color=#203060:life_color=#ffd040,trim=duration={dur},"
                f"scale=1280:720:flags=neighbor,hue=h={arg}")
    if kind == "cell":
        return f"cellauto=s=320x180:r=30:rule=110:scroll=1,trim=duration={dur},scale=1280:720:flags=neighbor,hue=h={arg}"
    if kind == "grad":
        return f"gradients=s=1280x720:r=30:d={dur}:speed=0.02:seed={arg}"
    if kind == "group":   # still picture (group photo)
        return f"color=c=0x4a6a3a:s=1280x720:r=30:d={dur},drawgrid=w=64:h=64:t=6:c=0xe0d0b0@0.8"
    if kind == "pan":   # ruhiger Kameraschwenk über ein breites Bild
        return (f"testsrc2=s=2560x720:r=30:d={dur},hue=h={arg},"
                f"crop=1280:720:'min(1280,t/{dur}*1280)':0")
    raise ValueError(kind)

AUDIO = {
    "musik": "0.18*(sin(2*PI*F*t)+0.6*sin(2*PI*F*1.26*t)+0.5*sin(2*PI*F*1.5*t)+0.3*sin(4*PI*F*t))".replace(
        "F", "(196*pow(2,floor(mod(t*1.5,4))*2/12))"),
    "applaus": "0.5*(random(0)*2-1)*pow(abs(sin(PI*t*9.3+3*sin(t*5.1))),12)+0.4*(random(1)*2-1)*pow(abs(sin(PI*t*7.1+2*sin(t*3.3))),12)+0.08*(random(2)*2-1)",
    "lachen": "0.3*(sin(2*PI*280*t)+0.5*sin(2*PI*560*t)+0.3*sin(2*PI*840*t))*pow(max(0,sin(2*PI*5*t)),2)*gt(mod(t,2.2),1.0)+0.04*(random(0)*2-1)",
    "sprache": "0.25*(sin(2*PI*(140+40*sin(2*PI*2.7*t))*t)+0.5*sin(4*PI*(140+40*sin(2*PI*2.7*t))*t))*pow(max(0,sin(2*PI*4.2*t)),1.5)*gt(mod(t,3.1),0.4)",
    "gruppe": "0.12*(sin(2*PI*(150+40*sin(2*PI*2.1*t))*t)*pow(max(0,sin(2*PI*4.1*t)),1.5)+sin(2*PI*(230+50*sin(2*PI*3.3*t))*t)*pow(max(0,sin(2*PI*3.7*t+1)),1.5)+sin(2*PI*(310+30*sin(2*PI*1.7*t))*t)*pow(max(0,sin(2*PI*4.9*t+2)),1.5))+0.06*(random(0)*2-1)",
    "jubel": "0.25*(random(0)*2-1)*(0.5+0.5*sin(2*PI*0.7*t))+0.2*sin(2*PI*(400+200*sin(2*PI*0.9*t))*t)*gt(mod(t,1.8),0.6)",
    "leise": "0.01*(random(0)*2-1)",
    "bus": "0.12*(random(0)+random(1)+random(2)-1.5)",
}

# (Zeit, [(Quelle, Dauer, Arg), …] Sichten, Ton, hochkant, Label, GPS, Spezial)
D1, D2, D3, D4 = "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"
clips = [
    (f"{D1} 09:10", [("bars", 8, 0)], "gruppe", False, "ANREISE Abfahrt", MS, ""),
    (f"{D1} 10:05", [("cell", 10, 60)], "bus", False, "ANREISE Bus innen", (53.0, 7.25), ""),
    (f"{D1} 10:40", [("bars", 7, 90), ("life", 7, 0)], "gruppe", False, "ANREISE Ankunft", JH, ""),
    (f"{D1} 10:50", [("smpte", 9, 0)], "sprache", True, "ANREISE Koffer", JH, ""),
    (f"{D1} 11:05", [("grad", 8, 1), ("bars", 7, 200)], "sprache", False, "ANMELDUNG Liste", JH, ""),
    (f"{D1} 11:15", [("life", 12, 270)], "lachen", False, "ARMBAND verteilen", JH, ""),
    (f"{D1} 11:20", [("grad", 6, 2)], "lachen", True, "ARMBAND Nahaufnahme", JH, ""),
    (f"{D1} 14:00", [("bars", 12, 30), ("cell", 12, 0), ("life", 12, 120), ("smpte", 12, 180)], "musik", False, "PROBE Orchester rundum", JH, ""),
    (f"{D1} 14:30", [("bars", 30, 30)], "musik", False, "PROBE Orchester fest", JH, ""),
    (f"{D1} 16:00", [("bars", 15, 0)], "jubel", False, "FREIZEIT Fussball WACKLIG", JH, "shake"),
    (f"{D1} 19:30", [("life", 12, 300), ("bars", 13, 300)], "applaus", False, "KENNENLERN Spiel", JH, ""),
    (f"{D1} 20:00", [("cell", 12, 30)], "lachen", False, "KENNENLERN Lachen", JH, ""),
    (f"{D2} 09:00", [("smpte", 12, 90), ("cell", 12, 200), ("bars", 11, 150)], "musik", False, "PROBE Blaeser", JH, ""),
    (f"{D2} 09:20", [("bars", 12, 0)], "musik", False, "PROBE UNSCHARF", JH, "blur"),
    (f"{D2} 11:00", [("life", 12, 60), ("grad", 13, 5)], "musik", False, "PROBE Streicher", JH, ""),
    (f"{D2} 13:00", [("smpte", 10, 300)], "gruppe", True, "FREIZEIT Mittagessen", JH, ""),
    (f"{D2} 15:00", [("cell", 10, 150), ("grad", 10, 7)], "lachen", False, "FREIZEIT Tischtennis", JH, ""),
    (f"{D2} 20:00", [("life", 18, 200)], "applaus", False, "FREIZEIT Spieleabend", JH, ""),
    (f"{D2} 21:15", [("bars", 10, 250)], "sprache", False, "FREIZEIT WhatsApp", None, "nometa"),
    (f"{D3} 09:30", [("smpte", 10, 220), ("life", 10, 330)], "musik", False, "PROBE Tag3", JH, ""),
    (f"{D3} 10:30", [("cell", 8, 90)], "bus", False, "AUSFLUG Busfahrt", (53.42, 7.40), ""),
    (f"{D3} 11:00", [("pan", 16, 0)], "leise", False, "MUSEUM AUSSEN Gebaeude", MUSEUM, "pan"),
    (f"{D3} 11:20", [("grad", 8, 9), ("smpte", 7, 120), ("life", 7, 180)], "gruppe", False, "MUSEUM Ausstellung", MUSEUM, ""),
    (f"{D3} 11:45", [("grad", 10, 11)], "lachen", True, "MUSEUM Experiment", MUSEUM, ""),
    (f"{D3} 16:00", [("bars", 10, 120), ("cell", 10, 250)], "jubel", False, "FREIZEIT Baden", JH, ""),
    (f"{D3} 21:00", [("life", 20, 90)], "musik", False, "FREIZEIT DISCO", JH, ""),
    (f"{D4} 09:00", [("smpte", 10, 45)], "sprache", False, "FREIZEIT Fruehstueck", JH, ""),
    (f"{D4} 10:00", [("cell", 10, 300), ("grad", 10, 13)], "musik", False, "REGISTERPROBE Dirigentin Floete", JH, ""),
    (f"{D4} 11:00", [("life", 8, 240), ("smpte", 8, 200)], "musik", True, "REGISTERPROBE Dirigentin Cello", JH, ""),
    (f"{D4} 13:30", [("group", 20, 0)], "sprache", False, "GRUPPENFOTO 1", JH, ""),
    (f"{D4} 13:33", [("group", 12, 0)], "lachen", False, "GRUPPENFOTO 2", JH, ""),
    (f"{D4} 14:00", [("life", 150, 0)], "musik", False, "KONZERT 1 fest", JH, ""),
    (f"{D4} 14:05", [("bars", 8, 160)], "musik", False, "KONZERT Seite", JH, ""),
    (f"{D4} 14:10", [("cell", 100, 40), ("smpte", 100, 270)], "musik", False, "KONZERT 2 zwei Plaetze", JH, ""),
    (f"{D4} 14:20", [("life", 120, 150)], "musik", True, "KONZERT 3 hochkant", JH, ""),
    (f"{D4} 14:30", [("bars", 10, 330)], "applaus", False, "KONZERT Applaus", JH, ""),
    (f"{D4} 15:30", [("bars", 15, 75)], "gruppe", False, "ABREISE Bus", JH, ""),
    (f"{D4} 15:32", [("smpte", 7, 140)], "jubel", True, "ABREISE winken", JH, ""),
]

def clip_name(ts, sp):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
    return f"VID_{t:%Y%m%d_%H%M%S}.mp4" if sp != "nometa" else f"WhatsApp Video {t:%Y-%m-%d} at {t:%H.%M.%S}.mp4"


def labels():
    """File name → label (category in capitals at the start)."""
    return {clip_name(c[0], c[6]): c[4] for c in clips}


def main(OUT, MUS):
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(MUS, exist_ok=True)
    for i, (ts, views, aud, portrait, label, gps, sp) in enumerate(clips):
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        utc = t - timedelta(hours=2)
        name = f"VID_{t:%Y%m%d_%H%M%S}.mp4" if sp != "nometa" else f"WhatsApp Video {t:%Y-%m-%d} at {t:%H.%M.%S}.mp4"
        out = os.path.join(OUT, name)
        if os.path.exists(out):
            continue
        dur = sum(v[1] for v in views)
        inputs, chains = [], []
        for j, (kind, d, arg) in enumerate(views):
            inputs += ["-f", "lavfi", "-i", src(kind, d, arg)]
            chains.append(f"[{j}:v]format=yuv420p,setsar=1[s{j}]")
        n = len(views)
        fc = ";".join(chains) + ";" + "".join(f"[s{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0[c]"
        vf = "[c]null"
        if portrait:
            vf += ",crop=405:720,scale=720:1280"
        if sp == "blur":
            vf += ",gblur=sigma=18"
        if sp == "shake":
            vf += ",pad=iw+120:ih+120:60:60,crop=iw-120:ih-120:'60+55*sin(t*23)':'60+50*cos(t*29)'"
        vf += (f",drawtext=fontfile={FONT}:text='{label}':x=40:y=40:fontsize=44:fontcolor=white:box=1:boxcolor=black@0.6,"
               f"drawtext=fontfile={FONT}:text='%{{pts\\:hms}}':x=40:y=105:fontsize=34:fontcolor=yellow:box=1:boxcolor=black@0.6,format=yuv420p[v]")
        ai = len(inputs) // 2 if False else n
        expr = AUDIO[aud]
        cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs +
               ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}",
                "-filter_complex", fc + ";" + vf, "-map", "[v]", "-map", f"{n}:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-g", "30", "-c:a", "aac", "-b:a", "64k", "-shortest"])
        if sp == "nometa":
            cmd += ["-map_metadata", "-1"]
        else:
            cmd += ["-metadata", f"creation_time={utc:%Y-%m-%dT%H:%M:%S}.000000Z"]
            if gps:
                cmd += ["-metadata", f"location={gps[0]:+08.4f}{gps[1]:+09.4f}/", "-movflags", "+use_metadata_tags"]
        subprocess.run(cmd + [out], check=True)
        print("ok", name, label, flush=True)

    # Testmusik mit klarem Beat; "Hot Swing" mit Schlussakkord und Stille am Ende
    for fname, bpm, dur, off in (("01 Morning Groove.mp3", 100, 150, 0.0), ("02 Fast Lane.mp3", 154, 200, 0.2),
                                 ("03 Swing Finale.mp3", 130, 170, 0.3)):
        p = 60.0 / bpm
        end = dur - 2.5
        expr = (f"if(lt(t,{off})+gt(t,{end}),0,"
                f"0.8*sin(2*PI*55*(t-{off}))*exp(-25*mod(t-{off},{p}))"
                f"+0.25*sin(2*PI*(440+110*floor(mod((t-{off})/{p},4)))*(t-{off}))*exp(-6*mod(t-{off},{p}))"
                f"+0.08*(random(0)-0.5)*exp(-60*mod(t-{off}+{p / 2},{p})))")
        out = os.path.join(MUS, fname)
        if not os.path.exists(out):
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"aevalsrc='{expr}|{expr}':s=44100:d={dur}", "-c:a", "libmp3lame", "-b:a", "128k", out],
                           check=True)
        print("ok", fname, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
