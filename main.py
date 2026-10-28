"""STAY DRIVEN autopilot.
  python main.py --kind long        # 6-8 min cinematic video -> YouTube + Facebook
  python main.py --kind short       # 40-55 sec vertical -> YouTube Shorts + FB Reel + IG Reel
  --dry-run       sudhu banabe, post korbe na
  --voice-test    koyekta voice er sample banabe (pochondo korar jonno)
"""
import argparse
import datetime as dt
import json
import random
import shutil
import sys
import traceback
from pathlib import Path

import yaml

from sd import audio, render, thumb, voice, writer
from sd.footage import Footage
from sd.util import ROOT, log

OUT = ROOT / "output"
HIST = ROOT / "data" / "history.json"


def load_history():
    h = json.loads(HIST.read_text()) if HIST.exists() else {}
    for k in ("posts", "used_footage", "long_formats", "short_styles"):
        h.setdefault(k, [])
    return h


def save_history(h):
    h["posts"] = h["posts"][-500:]
    h["used_footage"] = h["used_footage"][-5000:]
    h["long_formats"] = h["long_formats"][-20:]
    h["short_styles"] = h["short_styles"][-20:]
    HIST.write_text(json.dumps(h, indent=1))


def mmss(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def long_description(d, segs, cfg, music_note):
    chapters = ["0:00 " + "Intro"]
    for s in segs:
        if s.get("role") == "card":
            chapters.append(f"{mmss(s['start'])} {s['label'].title()}: {s['heading']}")
    close = next((s for s in segs if s.get("role") == "close"), None)
    if close:
        chapters.append(f"{mmss(close['start'])} Final Words")
    tags = " ".join(cfg["hashtags_youtube"])
    return (f"{d['description']}\n\n"
            + "\n".join(chapters)
            + f"\n\nA new video every day. Subscribe to {cfg['channel_name']} and turn on notifications.\n\n"
            + f"Footage: Pexels and Pixabay. {music_note}\n\n{tags}")


def run_kind(kind, cfg, hist, dry):
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    work = OUT / f"{day}_{kind}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    seed = random.randint(1, 10 ** 6)

    d = writer.write_long(cfg, hist) if kind == "long" else writer.write_short(cfg, hist)
    (work / "script.json").write_text(json.dumps(d, indent=1))
    parts = writer.to_timeline_parts(kind, d)
    voice_wav, total, segs = voice.synthesize(parts, cfg, work)

    # QUALITY GATE 1: captions must follow the voice the whole way
    from sd import align
    worst = align.check(segs, align.speech_mask(voice_wav), total)
    if worst > 3.0:
        raise RuntimeError(f"caption timing check failed ({worst:.1f}s of speech without captions)")

    used = set(hist["used_footage"])
    last_err = None
    for attempt in range(2):                       # QUALITY GATE 2: render retried once
        try:
            picker = Footage("landscape" if kind == "long" else "portrait", used).pick
            video, footage, shots = render.make_video(kind, segs, voice_wav, total, cfg, picker, work,
                                                      hook_text=d.get("hook_text"), seed=seed)
            break
        except Exception as e:
            last_err = e
            log(f"render attempt {attempt + 1} failed: {str(e)[:300]}")
            for f in work.glob("shot_*.mp4"):
                f.unlink()
    else:
        raise RuntimeError(f"render failed twice: {last_err}")
    music_note = "Music: " + ("licensed track." if audio.user_tracks() else "original score.")
    thumb_path = None
    if kind == "long":
        try:
            thumb_path = thumb.make(d["thumbnail_text"], d.get("thumbnail_scene", ""), footage, shots,
                                    work / "thumbnail.jpg", cfg.get("thumbnail_background", "auto"))
        except Exception as e:
            log(f"thumbnail failed: {e}")
    for f in list(work.glob("shot_*.mp4")) + list(work.glob("seg_*")) + list(work.glob("part_*")):
        f.unlink()

    rec = {"date": day, "kind": kind, "theme": d["theme"], "format": d["format"], "title": d["title"]}
    hist["used_footage"] = list(used)
    (hist["long_formats"] if kind == "long" else hist["short_styles"]).append(d["format"])
    errors = []
    if dry:
        log(f"DRY RUN: {video}")
        hist["posts"].append(rec)
        return errors

    if kind == "long":
        desc = long_description(d, segs, cfg, music_note)
        meta_text = f"{d['title']}\n\n{d['description']}\n\n{' '.join(cfg['hashtags_meta'])}"
    else:
        desc = (f"{d['caption']}\n\nNew motivation every day: subscribe to {cfg['channel_name']}.\n\n"
                + " ".join(cfg["hashtags_youtube"] + ["#shorts"]))
        meta_text = f"{d['caption']}\n.\n.\n{' '.join(cfg['hashtags_meta'])}"
    tags = d.get("tags") or []

    if cfg.get("youtube"):
        try:
            from sd import publish_youtube
            rec["youtube"] = publish_youtube.upload(video, d["title"], desc, tags, cfg, thumb=thumb_path,
                                                    srt=work / "captions.srt", comment=d.get("comment"))
        except Exception:
            traceback.print_exc()
            errors.append(f"YouTube {kind}")
    if cfg.get("facebook"):
        try:
            from sd import publish_meta
            rec["facebook"] = (publish_meta.fb_video(video, d["title"], meta_text) if kind == "long"
                               else publish_meta.fb_reel(video, meta_text))
        except Exception:
            traceback.print_exc()
            errors.append(f"Facebook {kind}")
    if cfg.get("instagram") and kind == "short":
        try:
            from sd import publish_meta
            rec["instagram"] = publish_meta.ig_reel(video, meta_text, cfg.get("meta_ai_label", True))
        except Exception:
            traceback.print_exc()
            errors.append("Instagram short")
    hist["posts"].append(rec)
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["long", "short"], default="short")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--voice-test", action="store_true")
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    OUT.mkdir(exist_ok=True)
    if a.voice_test:
        voice.voice_test(cfg, OUT / "voice-test")
        return
    hist = load_history()
    try:
        errors = run_kind(a.kind, cfg, hist, a.dry_run)
    finally:
        save_history(hist)
    if errors:
        log("FAILED: " + ", ".join(errors))
        sys.exit(1)
    log("DONE")


if __name__ == "__main__":
    main()
