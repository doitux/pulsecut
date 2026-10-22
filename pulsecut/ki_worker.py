"""KI-Worker – läuft in der eigenen KI-Umgebung (torch, sentence-transformers, transformers, faster-whisper).

Aufruf: python ki_worker.py auftrag.json
Aufgaben:
  bilder  – Bild-Merkmale (CLIP) je Einzelbild → .npy (float16, normiert)
  texte   – Text-Merkmale (mehrsprachiges CLIP, Deutsch geht direkt) → .npy
  ton     – Geräusche (AudioSet/AST): Musik, Applaus, Lachen, Jubel, Gruppe, Sprache → .jsonl
  sprache – Spracheingabe in Text umwandeln (Whisper) → .txt
Ausgaben auf stdout: MODELL …, FORTSCHRITT a b, FERTIG
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

AUDIO_GROUPS = {
    "musik": ["Music", "Musical instrument", "Orchestra", "Violin, fiddle", "Bowed string instrument", "Cello",
              "Brass instrument", "Trumpet", "Trombone", "French horn", "Wind instrument, woodwind instrument",
              "Flute", "Clarinet", "Saxophone", "Piano", "Keyboard (musical)", "Guitar", "Drum", "Drum kit",
              "Percussion", "Singing", "Choir", "Plucked string instrument", "Harp", "Accordion", "Glockenspiel",
              "Marimba, xylophone"],
    "applaus": ["Applause", "Clapping"],
    "lachen": ["Laughter", "Giggle", "Chuckle, chortle", "Belly laugh", "Snicker"],
    "jubel": ["Cheering", "Whoop", "Children shouting", "Shout", "Yell"],
    "gruppe": ["Crowd", "Hubbub, speech noise, speech babble", "Children playing", "Chatter"],
    "sprache": ["Speech", "Child speech, kid speaking", "Conversation", "Narration, monologue"],
}


def say(msg):
    print(msg, flush=True)


def main(jobfile):
    job = json.loads(Path(jobfile).read_text(encoding="utf-8"))
    import torch
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    models = job.get("modelle", {})
    aufg = job["aufgaben"]
    total = sum(len(a.get("items", [])) or 1 for a in aufg)
    done = 0
    for a in aufg:
        art = a["art"]
        if art == "bilder":
            from sentence_transformers import SentenceTransformer
            from PIL import Image
            say(f"MODELL Bild {models['bild']}")
            m = SentenceTransformer(models["bild"], device="cpu")
            for it in a["items"]:
                imgs = []
                for f in it["frames"]:
                    with Image.open(f) as im:
                        imgs.append(im.convert("RGB"))
                E = m.encode(imgs, batch_size=32, convert_to_numpy=True, normalize_embeddings=True,
                             show_progress_bar=False) if imgs else np.zeros((0, 512), np.float32)
                tmp = it["out"] + ".tmp.npy"
                np.save(tmp, E.astype(np.float16))
                os.replace(tmp, it["out"])
                done += 1
                say(f"FORTSCHRITT {done} {total}")
        elif art == "texte":
            from sentence_transformers import SentenceTransformer
            say(f"MODELL Text {models['text']}")
            m = SentenceTransformer(models["text"], device="cpu")
            E = m.encode(a["texte"], batch_size=32, convert_to_numpy=True, normalize_embeddings=True,
                         show_progress_bar=False)
            np.save(a["out"], E.astype(np.float32))
            done += 1
            say(f"FORTSCHRITT {done} {total}")
        elif art == "ton":
            from transformers import AutoFeatureExtractor, ASTForAudioClassification
            say(f"MODELL Ton {models['ton']}")
            fe = AutoFeatureExtractor.from_pretrained(models["ton"])
            try:
                am = ASTForAudioClassification.from_pretrained(models["ton"]).eval()
            except Exception:
                am = ASTForAudioClassification.from_pretrained(models["ton"], use_safetensors=False).eval()
            names = {str(v): int(k) for k, v in am.config.id2label.items()}
            groups = {g: [names[n] for n in lst if n in names] for g, lst in AUDIO_GROUPS.items()}
            sr, win, hop = 16000, 10.0, 5.0
            out = open(a["out"], "a", encoding="utf-8")
            with torch.inference_mode():
                for it in a["items"]:
                    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", it["pfad"],
                                        "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
                    y = np.frombuffer(p.stdout, np.float32)
                    dur = len(y) / sr
                    step = hop if dur <= 120 else 2 * hop
                    starts = [float(s) for s in np.arange(0.0, max(0.0, dur - win) + 1e-6, step)] or [0.0]
                    if dur > win and starts[-1] + win < dur - 1.0:
                        starts.append(dur - win)
                    res = {g: [] for g in groups}
                    for i in range(0, len(starts), 8):
                        chunk = [y[int(s * sr):int((s + win) * sr)] for s in starts[i:i + 8]]
                        chunk = [c if len(c) >= sr // 2 else np.pad(c, (0, sr // 2 - len(c))) for c in chunk]
                        feats = fe(chunk, sampling_rate=sr, return_tensors="pt")
                        pr = torch.sigmoid(am(**feats).logits).float().numpy()
                        for g, ids in groups.items():
                            res[g] += [round(float(pr[j, ids].max()), 3) if ids else 0.0 for j in range(len(chunk))]
                    out.write(json.dumps({"key": it["key"], "ton": {"t": [round(s, 2) for s in starts],
                                                                    "fenster": win, **res}}) + "\n")
                    out.flush()
                    done += 1
                    say(f"FORTSCHRITT {done} {total}")
            out.close()
        elif art == "sprache":
            from faster_whisper import WhisperModel
            say(f"MODELL Sprache {models['sprache']}")
            wm = WhisperModel(models["sprache"], device="cpu", compute_type="int8")
            # Audio selbst mit ffmpeg dekodieren: unabhängig von der PyAV-Version, die faster-whisper sonst nutzt
            p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", a["pfad"], "-vn",
                                "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True)
            audio = np.frombuffer(p.stdout, np.float32).copy()
            segs, _info = wm.transcribe(audio, language=a.get("sprache", "de"), vad_filter=True, beam_size=5)
            text = " ".join(s.text.strip() for s in segs).strip()
            Path(a["out"]).write_text(text, encoding="utf-8")
            done += 1
            say(f"FORTSCHRITT {done} {total}")
    say("FERTIG")


if __name__ == "__main__":
    main(sys.argv[1])
