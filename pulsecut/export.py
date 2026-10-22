"""Export: Kdenlive-Projekt (MLT) mit A/B-Spuren für Überblendungen, Titel, Rendern in verschiedenen Formaten."""
import json
import math
import os
import re
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from .i18n import L as _t
from .util import FPS, clean_env, ff_path, ffmpeg_cmd, find_font, fmt_dur, log, run, tc, write_png


class KdenliveWriter:
    def __init__(self):
        self.ids = 0

    def nid(self, prefix):
        self.ids += 1
        return f"{prefix}{self.ids}"

    @staticmethod
    def props(d, indent="  "):
        return "\n".join(f'{indent}<property name="{escape(k)}">{escape(str(v))}</property>'
                         for k, v in d.items() if v is not None)

    def filter_xml(self, props, fin=None, fout=None, indent="   "):
        fid = self.nid("filter")
        attrs = f' in="{tc(fin)}" out="{tc(fout)}"' if fin is not None else ""
        return f'{indent}<filter id="{fid}"{attrs}>\n' + self.props(props, indent + " ") + f"\n{indent}</filter>"

    def write(self, path, root, bin_items, tracks, total_frames, guides, folders, W=1920, H=1080, name="Film"):
        L = ["<?xml version='1.0' encoding='utf-8'?>",
             f'<mlt LC_NUMERIC="C" producer="main_bin" version="7.22.0" root="{escape(str(root))}">',
             f' <profile frame_rate_num="{FPS}" sample_aspect_num="1" display_aspect_den="{H // math.gcd(W, H)}" '
             f'colorspace="709" progressive="1" description="{W}x{H} {FPS} fps" '
             f'display_aspect_num="{W // math.gcd(W, H)}" frame_rate_den="1" '
             f'width="{W}" height="{H}" sample_aspect_den="1"/>']
        item_by_kid = {b["kid"]: b for b in bin_items}
        bin_ids = {}
        for b in bin_items:
            pid = self.nid("chain" if b["xmltag"] == "chain" else "producer")
            bin_ids[b["kid"]] = pid
            props = dict(b["base_props"])
            props.update(b.get("bin_props") or {})
            props["kdenlive:folderid"] = b["folder"]
            props["kdenlive:id"] = b["kid"]
            L.append(f' <{b["xmltag"]} id="{pid}" out="{tc(b["length"] - 1)}">')
            L.append(self.props(props))
            L.append(f' </{b["xmltag"]}>')
        L.append(f' <producer id="producer0" in="00:00:00.000" out="{tc(total_frames)}">')
        L.append(self.props({"length": 2147483647, "eof": "continue", "resource": "black", "aspect_ratio": 1,
                             "mlt_service": "color", "kdenlive:playlistid": "black_track",
                             "mlt_image_format": "rgba", "set.test_audio": 0}))
        L.append(" </producer>")
        inst_ids = {}

        def instance(kid, kind, tno):
            key = (kid, kind, tno)
            if key in inst_ids:
                return inst_ids[key]
            b = item_by_kid[kid]
            pid = self.nid("chain" if b["xmltag"] == "chain" else "producer")
            inst_ids[key] = pid
            props = dict(b["base_props"])
            props["kdenlive:folderid"] = b["folder"]
            props["kdenlive:id"] = kid
            props["xml"] = "was here"
            props["set.test_audio"] = 1 if kind == "video" else 0
            props["set.test_image"] = 0 if kind == "video" else 1
            L.append(f' <{b["xmltag"]} id="{pid}" out="{tc(b["length"] - 1)}">')
            L.append(self.props(props))
            L.append(f' </{b["xmltag"]}>')
            return pid

        track_tractors = []
        for tno, tr in enumerate(tracks):
            is_audio = tr["kind"] == "audio"
            for e in tr["entries"]:
                instance(e["kid"], "audio" if is_audio else "video", tno)
            pl1, pl2, tid = self.nid("playlist"), self.nid("playlist"), self.nid("tractor")
            L.append(f' <playlist id="{pl1}">')
            if is_audio:
                L.append('  <property name="kdenlive:audio_track">1</property>')
            pos = 0
            for e in sorted(tr["entries"], key=lambda e: e["pos"]):
                if e["pos"] > pos:
                    L.append(f'  <blank length="{tc(e["pos"] - pos)}"/>')
                pid = inst_ids[(e["kid"], "audio" if is_audio else "video", tno)]
                L.append(f'  <entry producer="{pid}" in="{tc(e["in"])}" out="{tc(e["out"])}">')
                L.append(f'   <property name="kdenlive:id">{e["kid"]}</property>')
                for fprops, fin, fout in e.get("filters", []):
                    if fin is not None:   # MLT: in/out von Eintrags-Filtern zählen in Quell-Frames
                        fin, fout = e["in"] + fin, e["in"] + fout
                    L.append(self.filter_xml(fprops, fin, fout))
                L.append("  </entry>")
                pos = e["pos"] + (e["out"] - e["in"] + 1)
            L.append(" </playlist>")
            L.append(f' <playlist id="{pl2}">' + ('\n  <property name="kdenlive:audio_track">1</property>\n </playlist>'
                                                 if is_audio else "</playlist>"))
            L.append(f' <tractor id="{tid}" in="00:00:00.000" out="{tc(total_frames - 1)}">')
            tp = {"kdenlive:audio_track": 1} if is_audio else {}
            tp.update({"kdenlive:track_name": tr["name"], "kdenlive:trackheight": 67, "kdenlive:timeline_active": 1,
                       "kdenlive:collapsed": 0, "kdenlive:thumbs_format": "", "kdenlive:audio_rec": ""})
            L.append(self.props(tp))
            hide = "video" if is_audio else "audio"
            L.append(f'  <track hide="{hide}" producer="{pl1}"/>')
            L.append(f'  <track hide="{hide}" producer="{pl2}"/>')
            if is_audio:
                L.append(self.filter_xml({"window": 75, "max_gain": "20dB", "mlt_service": "volume",
                                          "internal_added": 237, "disable": 1}, indent="  "))
                L.append(self.filter_xml({"channel": -1, "mlt_service": "panner", "internal_added": 237,
                                          "start": 0.5, "disable": 1}, indent="  "))
                L.append(self.filter_xml({"iec_scale": 0, "mlt_service": "audiolevel", "dbpeak": 1,
                                          "disable": 1}, indent="  "))
            L.append(" </tractor>")
            track_tractors.append((tid, is_audio))
        seq_uuid = "{" + str(uuid.uuid4()) + "}"
        seq_id = self.nid("tractor")
        n_audio = sum(1 for _, a in track_tractors if a)
        L.append(f' <tractor id="{seq_id}" in="00:00:00.000" out="{tc(total_frames - 1)}">')
        h, rem = divmod(total_frames, 3600 * FPS)
        m, rem = divmod(rem, 60 * FPS)
        s, fr = divmod(rem, FPS)
        guide_json = json.dumps([{"comment": g[1], "pos": int(g[0]), "type": g[2]} for g in guides], indent=4,
                                ensure_ascii=False)
        L.append(self.props({
            "kdenlive:duration": f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}", "kdenlive:maxduration": total_frames,
            "kdenlive:clipname": name, "kdenlive:description": "", "kdenlive:uuid": seq_uuid,
            "kdenlive:producer_type": 17, "kdenlive:id": folders["__seq_kid"], "kdenlive:clip_type": 0,
            "kdenlive:folderid": 2,
            "kdenlive:sequenceproperties.activeTrack": n_audio + 1,
            "kdenlive:sequenceproperties.audioChannels": 2, "kdenlive:sequenceproperties.audioTarget": -1,
            "kdenlive:sequenceproperties.disablepreview": 0, "kdenlive:sequenceproperties.documentuuid": seq_uuid,
            "kdenlive:sequenceproperties.hasAudio": 1, "kdenlive:sequenceproperties.hasVideo": 1,
            "kdenlive:sequenceproperties.position": 0, "kdenlive:sequenceproperties.scrollPos": 0,
            "kdenlive:sequenceproperties.tracks": len(track_tractors),
            "kdenlive:sequenceproperties.tracksCount": len(track_tractors),
            "kdenlive:sequenceproperties.verticalzoom": 1, "kdenlive:sequenceproperties.videoTarget": n_audio + 1,
            "kdenlive:sequenceproperties.zonein": 0, "kdenlive:sequenceproperties.zoneout": total_frames,
            "kdenlive:sequenceproperties.zoom": 8, "kdenlive:sequenceproperties.groups": "[\n]\n",
            "kdenlive:sequenceproperties.guides": guide_json + "\n"}))
        L.append('  <track producer="producer0"/>')
        for tid, _ in track_tractors:
            L.append(f'  <track producer="{tid}"/>')
        for i, (tid, is_audio) in enumerate(track_tractors, start=1):
            trid = self.nid("transition")
            if is_audio:
                tp = {"a_track": 0, "b_track": i, "mlt_service": "mix", "kdenlive_id": "mix", "internal_added": 237,
                      "always_active": 1, "accepts_blanks": 1, "sum": 1}
            else:
                tp = {"a_track": 0, "b_track": i, "compositing": 0, "distort": 0, "rotate_center": 0,
                      "mlt_service": "qtblend", "always_active": 1, "internal_added": 237}
            L.append(f'  <transition id="{trid}">\n' + self.props(tp, "   ") + "\n  </transition>")
        L.append(self.filter_xml({"window": 75, "max_gain": "20dB", "mlt_service": "volume", "internal_added": 237,
                                  "disable": 1}, indent="  "))
        L.append(self.filter_xml({"channel": -1, "mlt_service": "panner", "internal_added": 237, "start": 0.5,
                                  "disable": 1}, indent="  "))
        L.append(" </tractor>")
        L.append(' <playlist id="main_bin">')
        mp = {f"kdenlive:folder.-1.{fid}": name for name, fid in folders.items() if not name.startswith("__")}
        mp.update({
            "kdenlive:docproperties.activetimeline": seq_uuid, "kdenlive:docproperties.audioChannels": 2,
            "kdenlive:docproperties.browserurl": "", "kdenlive:docproperties.compositing": 1,
            "kdenlive:docproperties.documentid": int(time.time() * 1000),
            "kdenlive:docproperties.enableTimelineZone": 0, "kdenlive:docproperties.enableexternalproxy": 0,
            "kdenlive:docproperties.enableproxy": 0, "kdenlive:docproperties.externalproxyparams": "",
            "kdenlive:docproperties.generateimageproxy": 0, "kdenlive:docproperties.generateproxy": 0,
            "kdenlive:docproperties.kdenliveversion": "23.08.5",
            "kdenlive:docproperties.opensequences": seq_uuid, "kdenlive:docproperties.previewextension": "",
            "kdenlive:docproperties.previewparameters": "", "kdenlive:docproperties.profile": (f"atsc_1080p_{FPS}" if (W, H) == (1920, 1080) else ""),
            "kdenlive:docproperties.proxyextension": "", "kdenlive:docproperties.proxyimageminsize": 2000,
            "kdenlive:docproperties.proxyimagesize": 800, "kdenlive:docproperties.proxyminsize": 1000,
            "kdenlive:docproperties.proxyparams": "", "kdenlive:docproperties.proxyresize": 640,
            "kdenlive:docproperties.seekOffset": 30000, "kdenlive:docproperties.uuid": seq_uuid,
            "kdenlive:docproperties.version": "1.1", "kdenlive:docproperties.patchversion": 1,
            "kdenlive:expandedFolders": "", "kdenlive:binZoom": 4,
            "kdenlive:documentnotes": _t("Automatisch erzeugt mit Pulsecut"), "xml_retain": 1})
        L.append(self.props(mp))
        for b in bin_items:
            L.append(f'  <entry producer="{bin_ids[b["kid"]]}" in="00:00:00.000" out="{tc(b["length"] - 1)}"/>')
        L.append(f'  <entry producer="{seq_id}" in="00:00:00.000" out="{tc(total_frames - 1)}"/>')
        L.append(" </playlist>")
        proj = self.nid("tractor")
        L.append(f' <tractor id="{proj}" in="00:00:00.000" out="{tc(total_frames - 1)}">')
        L.append('  <property name="kdenlive:projectTractor">1</property>')
        L.append(f'  <track producer="{seq_id}" in="00:00:00.000" out="{tc(total_frames - 1)}"/>')
        L.append(" </tractor>")
        L.append("</mlt>")
        Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def fade_from_black(nframes):
    return ({"start": 1, "level": "0=0;-1=1", "alpha": 1, "mlt_service": "brightness",
             "kdenlive_id": "fade_from_black", "kdenlive:collapsed": 0}, 0, max(1, nframes - 1))


def fade_to_black(clip_frames, nframes):
    return ({"start": 1, "level": "0=1;-1=0", "alpha": 1, "mlt_service": "brightness",
             "kdenlive_id": "fade_to_black", "kdenlive:collapsed": 0}, clip_frames - nframes, clip_frames - 1)


def alpha_fade_in(nframes):
    return ({"start": 1, "level": 1, "alpha": "0=0;-1=1", "mlt_service": "brightness",
             "kdenlive_id": "fade_from_black", "kdenlive:collapsed": 0}, 0, max(1, nframes - 1))


def alpha_fade_out(clip_frames, nframes):
    return ({"start": 1, "level": 1, "alpha": "0=1;-1=0", "mlt_service": "brightness",
             "kdenlive_id": "fade_to_black", "kdenlive:collapsed": 0}, clip_frames - nframes, clip_frames - 1)


def audio_fade_in(nframes):
    return ({"gain": 0, "end": 1, "mlt_service": "volume", "kdenlive_id": "fadein", "kdenlive:collapsed": 0},
            0, max(1, nframes - 1))


def audio_fade_out(clip_frames, nframes):
    return ({"gain": 1, "end": 0, "mlt_service": "volume", "kdenlive_id": "fadeout", "kdenlive:collapsed": 0},
            clip_frames - nframes, clip_frames - 1)


def volume_kf(n, keys, smooth=False):
    """Lautstärke-Effekt mit Keyframes (Frames relativ zum Clipanfang → dB); smooth = weiche Kurve."""
    sep = "~=" if smooth else "="
    s = ";".join(f"{tc(max(0, min(n - 1, f)))}{sep}{db:.1f}" for f, db in keys)
    return ({"level": s, "mlt_service": "volume", "kdenlive_id": "volume", "kdenlive:collapsed": 0}, 0, n - 1)


def gain_filter(db):
    return ({"level": f"{db:.1f}", "mlt_service": "volume", "kdenlive_id": "volume", "kdenlive:collapsed": 0},
            None, None)


def zoom_filter(n, z, WIDTH=1920, HEIGHT=1080):
    """Langsame Zoomfahrt (Ken Burns) um z (0,1 = 10 %)."""
    w2, h2 = WIDTH * (1 + z), HEIGHT * (1 + z)
    r0 = f"0 0 {WIDTH} {HEIGHT} 1.000000"
    r1 = f"{-(w2 - WIDTH) / 2:.0f} {-(h2 - HEIGHT) / 2:.0f} {w2:.0f} {h2:.0f} 1.000000"
    a, b = tc(0), tc(n - 1)   # alle animierbaren Parameter brauchen dieselben Keyframes (sonst Kdenlive-Warnung)
    return ({"rect": f"{a}={r0};{b}={r1}", "rotation": f"{a}=0;{b}=0", "compositing": 0, "distort": 0,
             "rotate_center": 1, "rotate_anchor": f"{a}=0.5 0.5;{b}=0.5 0.5", "mlt_service": "qtblend",
             "kdenlive_id": "qtblend", "kdenlive:collapsed": 0}, 0, n - 1)


def bg_filters(clip, WIDTH=1920, HEIGHT=1080):
    a = clip.aspect
    if a < 16 / 9:
        w, h = WIDTH, WIDTH / a
    else:
        h, w = HEIGHT, HEIGHT * a
    x, y = (WIDTH - w) / 2, (HEIGHT - h) / 2
    return [
        ({"hradius": 30, "vradius": 30, "preserve_alpha": 0, "mlt_service": "box_blur", "kdenlive_id": "box_blur",
          "kdenlive:collapsed": 0}, None, None),
        ({"rect": f"{x:.0f} {y:.0f} {w:.0f} {h:.0f} 1.000000", "rotation": 0, "compositing": 0, "distort": 0,
          "rotate_center": 1, "rotate_anchor": "0.5 0.5", "mlt_service": "qtblend", "kdenlive_id": "qtblend",
          "kdenlive:collapsed": 0}, None, None),
        ({"start": 1, "level": 0.55, "mlt_service": "brightness", "kdenlive_id": "brightness",
          "kdenlive:collapsed": 0}, None, None),
    ]




# ═════════════════════════════════════════════ Titel

def make_title_png(out, lines, band_y, band_h, tmpdir, W=1920, H=1080):
    """Titel als transparentes PNG (weiße Schrift mit Schatten auf weichem dunklen Band)."""
    sc = W / 1920 if W >= H else W / 1080
    bold, reg = find_font(True), find_font(False) or find_font(True)
    filters = ["null"]
    total = sum(int(s * sc * 1.35) for _, s, _ in lines)
    y = band_y + (band_h - total) // 2
    tfiles = []
    for i, (text, size, is_bold) in enumerate(lines):
        size = int(size * sc)
        tf = Path(tmpdir) / f"titel_{Path(out).stem}_{i}.txt"
        tf.write_text(text, encoding="utf-8")
        tfiles.append(tf)
        font = bold if is_bold else reg
        fo = f"fontfile='{ff_path(font)}':" if font else ""
        filters.append(f"drawtext={fo}textfile='{ff_path(tf)}':expansion=none:fontsize={size}:fontcolor=white:"
                       f"shadowcolor=black@0.7:shadowx=3:shadowy=3:x=(w-text_w)/2:y={y}")
        y += int(size * 1.35)
    raw = run(ffmpeg_cmd() + ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H},format=rgba", "-vf",
                              ",".join(filters) + ",format=rgba", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                              "rgba", "-"], binary=True)
    for tf in tfiles:
        tf.unlink(missing_ok=True)
    txt = np.frombuffer(raw, np.uint8).reshape(H, W, 4).astype(np.float32) / 255.0
    ys = np.arange(H)
    lower = (band_y + band_h - ys) if band_y + band_h < H else np.full(H, 1e6)
    ba = np.clip(np.minimum(ys - band_y, lower) / (50.0 * sc) + 0.5, 0, 1) * 0.45
    a_t = txt[..., 3:4]
    a_b = np.broadcast_to(ba[:, None, None], a_t.shape)
    a_o = a_t + a_b * (1 - a_t)
    rgb = (txt[..., :3] * a_t) / np.maximum(a_o, 1e-6)
    write_png(out, (np.clip(np.concatenate([rgb, a_o], axis=2), 0, 1) * 255 + 0.5).astype(np.uint8))


def title_pngs(titles, outdir, tmpdir, W, H):
    res = []
    for j, t in enumerate(titles):
        lines = [(t["text"], 92 if j == 0 else 60, True)] + ([(t["unter"], 46, False)] if t.get("unter") else [])
        p = Path(outdir) / f"titel_{j}_{W}x{H}.png"
        if W >= H:
            by, bh = (690, 230 if t.get("unter") else 170) if j == 0 else (840, 200)
            by, bh = int(by * H / 1080), int(bh * H / 1080)
        else:
            by, bh = int(H * 0.68), int(H * 0.14)
        make_title_png(p, lines, by, bh, tmpdir, W, H)
        res.append((p, t["t0"], t["t1"]))
    return res


# ═════════════════════════════════════════════ Originalton-Einträge

def atmo_entries(shots, total_frames, clips):
    """Originalton je Gruppe: weich ein/aus, zwischen den Clips überblendet (abwechselnd auf zwei Spuren)."""
    runs, cur = [], []
    for s in shots:
        a = s.get("atmo")
        if a and cur and cur[-1]["atmo"]["gruppe"] == a["gruppe"] and cur[-1]["f1"] == s["f0"]:
            cur.append(s)
            continue
        if cur:
            runs.append(cur)
        cur = [s] if a else []
    if cur:
        runs.append(cur)
    out, lane = [], 0
    for run_ in runs:
        for j, s in enumerate(run_):
            c = clips[s["clip"]]
            n = s["f1"] - s["f0"]
            first, last = j == 0, j == len(run_) - 1
            maxf = int(math.floor(c.dur * FPS)) - 1
            pre = min(0 if first else int(0.3 * FPS), s["src_f"], s["f0"])
            post = max(0, min(int((0.8 if last else 0.3) * FPS), maxf - (s["src_f"] + n - 1), total_frames - s["f1"]))
            ln = pre + n + post
            fi = min(int((1.2 if first else 0.6) * FPS), ln // 2)
            fo = min(int((1.6 if last else 0.6) * FPS), ln // 2)
            out.append({"clip": c, "pos": s["f0"] - pre, "in": s["src_f"] - pre, "out": s["src_f"] + n - 1 + post,
                        "len": ln, "gain": s["atmo"]["gain_db"], "fi": fi, "fo": fo, "lane": lane,
                        "first": first, "last": last})
            lane = 1 - lane
    return out


# ═════════════════════════════════════════════ Projekt schreiben

def frame_plan(shots, D, xf):
    """Frames je Schnitt; bei Überblendung mit Rändern (A/B-Spuren)."""
    total = int(round(D * FPS))
    h = int(round(xf * FPS / 2)) if xf > 0 else 0
    out = []
    for i, s in enumerate(shots):
        f0 = int(math.floor(s["tl0"] * FPS + 0.45))
        f1 = int(math.floor(s["tl1"] * FPS + 0.45)) if s["tl1"] < D - 0.01 else total
        src_f = int(round(s["src"] * FPS))
        a = h if i > 0 else 0
        b = h if i < len(shots) - 1 else 0
        out.append(dict(s, f0=f0, f1=f1, src_f=src_f, e0=f0 - a, e1=f1 + b, ein=src_f - a, lane=i % 2 if h else 0,
                        hf=a, hb=b))
    return out, total


def write_project(pr, path, W=1920, H=1080, mit_marker=True):
    """Schreibt das Kdenlive-Projekt für die aktuelle Timeline. Gibt (Pfad, Titel, Gesamtframes) zurück."""
    info = pr.timeline_info()
    shots = [s for s in info["shots"] if not s["ueber"] and s["dur"] > 0]
    if not shots:
        raise RuntimeError(_t("Die Timeline ist leer."))
    D = info["dauer"]
    xf = info["xf"]
    clips = pr.clip_by_name()
    pr.atmo_plan(shots)
    fp, total = frame_plan(shots, D, xf)
    out_aspect = W / H
    kw = KdenliveWriter()
    folders = {_t("Sequenzen"): 2, _t("Videos"): 3, _t("Musik"): 4, _t("Titel"): 5, "__seq_kid": 6}   # Name → Ordner-ID
    bin_items, kid = [], 10
    used = sorted({s["clip"]: clips[s["clip"]] for s in shots}.values(), key=lambda c: c.start)
    kids = {}
    for c in used:
        kids[c.name] = kid
        length = int(math.floor(c.dur * FPS))
        bin_items.append({"kid": kid, "xmltag": "chain", "folder": 3, "length": length, "base_props": {
            "length": length, "eof": "pause", "resource": str(c.path), "mlt_service": "avformat-novalidate",
            "seekable": 1, "kdenlive:clipname": "", "kdenlive:clip_type": 0, "mute_on_pause": 0}})
        kid += 1
    L = pr.layout
    tkid = {}
    for i, t in enumerate(L.tracks):
        tkid[i] = kid
        length = int(math.floor(t["dur"] * FPS))
        t["_frames"] = length
        markers = [{"comment": _t("Takt {n}", n=j + 1), "pos": int(round(b * FPS)), "type": 0}
                   for j, b in enumerate(b for b, d in zip(t["beats"], t["down"]) if d)] if mit_marker else []
        bin_items.append({"kid": kid, "xmltag": "chain", "folder": 4, "length": length, "base_props": {
            "length": length, "eof": "pause", "resource": t["path"], "mlt_service": "avformat-novalidate",
            "seekable": 1, "kdenlive:clipname": "", "kdenlive:clip_type": 1, "video_index": -1,
            "mute_on_pause": 0}, "bin_props": {"kdenlive:markers": json.dumps(markers, indent=1)}})
        kid += 1
    titles = title_pngs(info["titel"], pr.dirs["titel"], pr.dirs["tmp"], W, H)
    title_items = []
    for png, t0, t1 in titles:
        n = int(round((t1 - t0) * FPS))
        bin_items.append({"kid": kid, "xmltag": "producer", "folder": 5, "length": n, "base_props": {
            "length": n, "eof": "pause", "resource": str(png), "ttl": 25, "aspect_ratio": 1, "progressive": 1,
            "seekable": 1, "mlt_service": "qimage", "kdenlive:clipname": png.stem}})
        title_items.append((kid, int(round(t0 * FPS)), n))
        kid += 1
    vA_bg, vA, vB_bg, vB, vT = [], [], [], [], []
    end_f = int(1.5 * FPS)
    for s in fp:
        c = clips[s["clip"]]
        n = s["e1"] - s["e0"]
        if s["ein"] < 0:   # sollte durch die Planung nie passieren
            s["ein"], n = 0, n + s["ein"]
        ent = {"pos": s["e0"], "kid": kids[c.name], "in": s["ein"], "out": s["ein"] + n - 1}
        fl = []
        if s["e0"] == 0:
            fl.append(fade_from_black(min(FPS, n)))
        if s["e1"] > total - end_f:
            fl.append(fade_to_black(n, s["e1"] - max(s["e0"], total - end_f)))
        if s["lane"] == 1:   # obere Spur blendet über die untere ein und wieder aus
            if s["hf"]:
                fl.append(alpha_fade_in(2 * s["hf"]))
            if s["hb"]:
                fl.append(alpha_fade_out(n, 2 * s["hb"]))
        bg = c.needs_bg(out_aspect)
        main, bgl = (vB, vB_bg) if s["lane"] == 1 else (vA, vA_bg)
        if bg:
            bgl.append(dict(ent, filters=bg_filters(c, W, H) + fl))
        main.append(dict(ent, filters=list(fl)))
    a1, a2, a3, a4 = [], [], [], []
    for e in atmo_entries(fp, total, clips):
        ln, g = e["len"], e["gain"]
        fi, fo = e["fi"], e["fo"]
        lo_in, lo_out = (-40.0 if e["first"] else -24.0), (-40.0 if e["last"] else -24.0)
        keys = [(0, g + lo_in), (fi // 3, g - 9.5), (2 * fi // 3, g - 3.5), (fi, g),
                (ln - 1 - fo, g), (ln - 1 - 2 * fo // 3, g - 3.5), (ln - 1 - fo // 3, g - 9.5), (ln - 1, g + lo_out)]
        keys = [k for i, k in enumerate(keys) if i == 0 or k[0] > keys[i - 1][0]]
        (a3 if e["lane"] == 0 else a4).append({"pos": e["pos"], "kid": kids[e["clip"].name], "in": e["in"],
                                               "out": e["out"], "filters": [volume_kf(ln, keys, smooth=True)]})
    for tk, p0, n in title_items:
        fl = [alpha_fade_in(min(15, n // 3))]
        fl.append(fade_to_black(n, min(end_f, n)) if p0 + n >= total - 1 else alpha_fade_out(n, min(15, n // 3)))
        vT.append({"pos": p0, "kid": tk, "in": 0, "out": n - 1, "filters": fl})
    for sg in L.segments:
        tr = L.tracks[sg["track"]]
        p0 = int(round(sg["tl_start"] * FPS))
        fin = int(round(sg["src_in"] * FPS))
        if p0 < 0:
            fin, p0 = fin - p0, 0
        n = min(int(round((sg["src_out"] - sg["src_in"]) * FPS)), tr["_frames"] - fin, total - p0)
        if n <= 1:
            continue
        fl = []
        if sg["fade_in"] > 0:
            fl.append(audio_fade_in(max(2, int(sg["fade_in"] * FPS))))
        if sg["fade_out"] > 0:
            fl.append(audio_fade_out(n, max(2, int(sg["fade_out"] * FPS))))
        (a1 if sg["lane"] == 0 else a2).append({"pos": p0, "kid": tkid[sg["track"]], "in": fin, "out": fin + n - 1,
                                                "filters": fl})
    tracks = [{"kind": "audio", "name": _t("Originalton 2"), "entries": a4},
              {"kind": "audio", "name": _t("Originalton"), "entries": a3},
              {"kind": "audio", "name": _t("Musik 2"), "entries": a2},
              {"kind": "audio", "name": _t("Musik"), "entries": a1},
              {"kind": "video", "name": _t("Hintergrund A"), "entries": vA_bg},
              {"kind": "video", "name": "Video A", "entries": vA}]
    if xf > 0:
        tracks += [{"kind": "video", "name": _t("Hintergrund B"), "entries": vB_bg},
                   {"kind": "video", "name": "Video B", "entries": vB}]
    tracks.append({"kind": "video", "name": _t("Titel"), "entries": vT})
    guides, prev = [], None
    for s in fp:
        if s["kw"] != prev:
            guides.append((s["f0"], s["name"] or _t("Szene"), 0))
            prev = s["kw"]
    kw.write(path, pr.ordner, bin_items, tracks, total, guides, folders, W, H, pr.d["name"])
    return path, total


# ═════════════════════════════════════════════ Rendern

FORMATE = {
    "1080p": {"label": "Full HD 1080p (MP4, H.264)", "W": 1920, "H": 1080, "ext": "mp4",
              "args": ["vcodec=libx264", "crf=18", "preset=medium", "acodec=aac", "ab=256k", "f=mp4",
                       "movflags=+faststart", "pix_fmt=yuv420p"]},
    "4k": {"label": "4K UHD (MP4, H.264)", "W": 3840, "H": 2160, "ext": "mp4",
           "args": ["vcodec=libx264", "crf=19", "preset=medium", "acodec=aac", "ab=256k", "f=mp4",
                    "movflags=+faststart", "pix_fmt=yuv420p"]},
    "720p": {"label": "HD 720p (MP4, klein für Mail/Messenger)", "W": 1280, "H": 720, "ext": "mp4",
             "args": ["vcodec=libx264", "crf=23", "preset=medium", "acodec=aac", "ab=160k", "f=mp4",
                      "movflags=+faststart", "pix_fmt=yuv420p"]},
    "hochformat": {"label": "Hochformat 9:16 (1080×1920, Reels/Status)", "W": 1080, "H": 1920, "ext": "mp4",
                   "args": ["vcodec=libx264", "crf=19", "preset=medium", "acodec=aac", "ab=192k", "f=mp4",
                            "movflags=+faststart", "pix_fmt=yuv420p"]},
    "master": {"label": "Master-Qualität (MOV, ProRes 422 HQ)", "W": 1920, "H": 1080, "ext": "mov",
               "args": ["vcodec=prores_ks", "vprofile=3", "acodec=pcm_s16le", "f=mov", "pix_fmt=yuv422p10le"]},
}


def render_melt(xml, out, fmt, progress=None):
    """Rendert eine MLT/Kdenlive-Datei mit melt (dieselbe Engine wie Kdenlive)."""
    F = FORMATE[fmt]
    tmp = Path(str(out) + ".teil." + F["ext"])
    cmd = ["melt", "-progress", str(xml), "-consumer", f"avformat:{tmp}", "real_time=-2", "terminate_on_pause=1",
           f"threads={max(1, (os.cpu_count() or 2))}"] + F["args"]
    env = clean_env()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, stdin=subprocess.DEVNULL)
    buf, tail = b"", []
    while True:
        ch = p.stderr.read(256)
        if not ch:
            break
        buf += ch
        parts = re.split(rb"[\r\n]", buf)
        buf = parts[-1]
        for line in parts[:-1]:
            s = line.decode("utf-8", "replace")
            m = re.search(r"percentage:\s*(\d+)", s)
            if m and progress:
                progress(int(m.group(1)) / 100.0)
            elif s.strip():
                tail.append(s.strip())
                del tail[:-20]
    p.wait()
    if p.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        raise RuntimeError(_t("melt-Rendern fehlgeschlagen: ") + " | ".join(tail[-5:])[-500:])
    tmp.replace(out)
    return out


def render_ffmpeg(pr, out, fmt, progress=None):
    """Ersatz ohne melt: harte Schnitte, Titel, Musik, Originalton – alles mit ffmpeg."""
    F = FORMATE[fmt]
    W, H = F["W"], F["H"]
    info = pr.timeline_info()
    shots = [s for s in info["shots"] if not s["ueber"] and s["dur"] > 0]
    D = info["dauer"]
    clips = pr.clip_by_name()
    pr.atmo_plan(shots)
    fp, total = frame_plan(shots, D, 0.0)
    tmpdir = pr.dirs["tmp"] / f"render_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    done = [0]

    def one(i_s):
        i, s = i_s
        c = clips[s["clip"]]
        n = s["f1"] - s["f0"]
        d = n / FPS
        p = tmpdir / f"teil_{i:04d}.mp4"
        if c.needs_bg(W / H):
            vf = (f"split=2[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"boxblur=20:2,eq=brightness=-0.25[b];[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[f];"
                  f"[b][f]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p")
        else:
            vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p"
        run(ffmpeg_cmd() + ["-y", "-ss", f"{s['src_f'] / FPS:.3f}", "-i", str(c.path), "-t", f"{d + 0.5:.3f}", "-an",
                            "-filter_complex", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium",
                            "-crf", "17", "-g", "50", str(p)])
        done[0] += 1
        if progress:
            progress(0.85 * done[0] / len(fp))
        return p

    with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2) // 2))) as ex:
        parts = list(ex.map(one, enumerate(fp)))
    lst = tmpdir / "teile.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    video = tmpdir / "video.mp4"
    run(ffmpeg_cmd() + ["-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    ins, fl = pr.layout.ffmpeg_mix_args(D)
    idx = len(pr.layout.segments)
    atmo = []
    for e in atmo_entries(fp, total, clips):
        d = e["len"] / FPS
        ins += ["-ss", f"{e['in'] / FPS:.3f}", "-t", f"{d:.3f}", "-i", str(e["clip"].path)]
        ms = int(round(e["pos"] / FPS * 1000))
        fl.append(f"[{idx}:a]aformat=channel_layouts=stereo,volume={e['gain']}dB,afade=t=in:d={e['fi'] / FPS:.2f}:curve=tri,"
                  f"afade=t=out:st={max(0, d - e['fo'] / FPS):.2f}:d={e['fo'] / FPS:.2f}:curve=tri,adelay={ms}|{ms}[at{idx}]")
        atmo.append(f"[at{idx}]")
        idx += 1
    if atmo:
        fl.append(f"[musik]{''.join(atmo)}amix=inputs={1 + len(atmo)}:normalize=0:duration=first,atrim=0:{D:.3f}[aout]")
    else:
        fl.append(f"[musik]anull[aout]")
    vin = idx
    ins += ["-i", str(video)]
    vchain = f"[{vin}:v]null[v0]"
    last = "v0"
    for j, (png, t0, t1) in enumerate(title_pngs(info["titel"], pr.dirs["titel"], pr.dirs["tmp"], W, H)):
        ins += ["-loop", "1", "-t", f"{t1:.3f}", "-i", str(png)]
        ii = vin + 1 + j
        vchain += (f";[{ii}:v]format=rgba,fade=t=in:st={t0:.2f}:d=0.6:alpha=1,fade=t=out:st={t1 - 0.6:.2f}:d=0.6:alpha=1[t{j}];"
                   f"[{last}][t{j}]overlay=0:0:enable='between(t,{t0:.2f},{t1:.2f})'[v{j + 1}]")
        last = f"v{j + 1}"
    vchain += f";[{last}]fade=t=in:d=1,fade=t=out:st={D - 1.5:.2f}:d=1.5[vout]"
    ext = F["ext"]
    venc = ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"] if fmt == "master" else \
        ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart"]
    tmp_out = Path(str(out) + ".teil." + ext)
    run(ffmpeg_cmd() + ["-y"] + ins + ["-filter_complex", ";".join(fl) + ";" + vchain, "-map", "[vout]", "-map",
                                       "[aout]"] + venc + ["-t", f"{D:.3f}", str(tmp_out)])
    tmp_out.replace(out)
    for p in tmpdir.glob("*"):
        p.unlink(missing_ok=True)
    tmpdir.rmdir()
    if progress:
        progress(1.0)
    return out
