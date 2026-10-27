"""Voiceover: Gemini TTS (natural, free tier) -> na hole Edge TTS. Word timing shoho."""
import asyncio
import base64
import os
import re
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import requests

from .util import ffprobe_duration, log, run

TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-3.8-flash-lite-tts",
              "gemini-2.5-flash-preview-tts"]
EXHAUSTED = set()
PART_GAP = 0.55      # part er majhe (hook -> point) ektu dom
CARD_GAP = 0.35


# ---------------- Gemini ----------------
def _find_audio(obj):
    found = []

    def walk(o):
        if isinstance(o, dict):
            data = o.get("data")
            mime = str(o.get("mimeType") or o.get("mime_type") or "")
            if isinstance(data, str) and len(data) > 200 and ("audio" in mime or o.get("type") == "audio"):
                found.append((data, mime))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return found[-1] if found else (None, "")


def _to_wav(raw, mime, path):
    if raw[:4] == b"RIFF":
        Path(path).write_bytes(raw)
        return
    m = re.search(r"rate=(\d+)", mime or "")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(m.group(1)) if m else 24000)
        w.writeframes(raw)


def gemini_tts(text, voice, path):
    key = os.environ["GEMINI_API_KEY"]
    last = ""
    for model in TTS_MODELS:
        if model in EXHAUSTED:
            continue
        styles = [
            ("generateContent", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
             {"contents": [{"parts": [{"text": text}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}),
            ("interactions", "https://generativelanguage.googleapis.com/v1beta/interactions",
             {"model": model, "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
              "response_format": {"type": "audio"},
              "generation_config": {"speech_config": [{"voice": voice}]}}),
        ]
        for style, url, body in styles:
            if model in EXHAUSTED:
                break
            for retry in range(3):
                try:
                    r = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=300)
                    if r.status_code != 200:
                        msg = r.text[:300]
                        last = f"{model} {style}: HTTP {r.status_code} {msg}"
                        if r.status_code == 429 and re.search(r"per day|PerDay|daily", msg, re.I):
                            EXHAUSTED.add(model)
                            log("TTS daily limit: " + model)
                            break
                        if r.status_code in (429, 500, 502, 503, 504) and retry < 2:
                            time.sleep(30 * (retry + 1))
                            continue
                        break
                    b64, mime = _find_audio(r.json())
                    if not b64:
                        last = f"{model} {style}: no audio"
                        break
                    _to_wav(base64.b64decode(b64), mime, path)
                    return model
                except Exception as e:
                    last = f"{model} {style}: {e}"
                    time.sleep(5)
    raise RuntimeError("Gemini TTS failed: " + last[:300])


# ---------------- Edge ----------------
async def _edge(text, cfg, path, voice=None):
    import edge_tts
    comm = edge_tts.Communicate(text, voice or cfg["edge_voice"], rate=cfg["edge_rate"],
                                pitch=cfg["edge_pitch"], boundary="WordBoundary")
    words = []
    with open(path, "wb") as fh:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7,
                              "word": ch["text"]})
    return words


def edge_tts_file(text, cfg, path, voice=None):
    for attempt in range(4):
        try:
            return asyncio.run(_edge(text, cfg, path, voice))
        except Exception as e:
            log(f"edge retry {attempt + 1}: {e}")
            time.sleep(5)
    raise RuntimeError("Edge TTS failed")


# ---------------- helpers ----------------
def _wav48(src, dst, pad_before=0.0, pad_after=0.0):
    af = []
    if pad_before:
        af.append(f"adelay={int(pad_before * 1000)}:all=1")
    af.append("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
    af.append(f"apad=pad_dur={pad_after:.3f}")
    # tiny warmth + presence so the voice sits like a studio narrator
    af.append("highpass=f=70,bass=g=2.5:f=120,equalizer=f=3200:t=q:w=1.2:g=1.5")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", ",".join(af),
         "-ar", "48000", "-ac", "1", str(dst)])


def _fake(text, path):
    secs = max(1.2, len(text.split()) / 2.5)
    t = np.arange(int(secs * 24000)) / 24000.0
    sig = 0.2 * np.sin(2 * np.pi * 160 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    _to_wav((sig * 32767).astype("<i2").tobytes(), "audio/L16;rate=24000", path)


def _even(text, start, dur):
    toks = text.split()
    tot = sum(len(t) + 2 for t in toks) or 1
    out, t = [], start
    for w in toks:
        d = dur * (len(w) + 2) / tot
        out.append({"start": t, "end": t + d * 0.92, "word": w})
        t += d
    return out


def _concat(wavs, out):
    lst = out.parent / (out.stem + "_list.txt")
    lst.write_text("".join(f"file '{Path(w).name}'\n" for w in wavs))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
         "-c", "copy", out.name], cwd=out.parent)


# ---------------- main ----------------
def synthesize(parts, cfg, work: Path):
    """parts: [[segment,...], ...]  ->  (voice.wav, total_sec, flat segments with start/dur/words)"""
    work.mkdir(parents=True, exist_ok=True)
    fake = os.environ.get("SD_FAKE_TTS") == "1"
    engine = "fake" if fake else cfg.get("voice_engine", "gemini")
    if engine == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        engine = "edge"
    if engine == "gemini":
        try:
            return _synth_gemini(parts, cfg, work)
        except Exception as e:
            log(f"Gemini voice failed ({str(e)[:200]}), using Edge voice for the whole video")
            engine = "edge"
    return _synth_per_segment(parts, cfg, work, engine)


def _synth_gemini(parts, cfg, work):
    from .align import align_words
    wavs, segs, cursor = [], [], 0.0
    for pi, part in enumerate(parts):
        raw = work / f"part_{pi:02d}_raw.wav"
        text = " ".join(s["text"] for s in part)
        model = gemini_tts(text, cfg["gemini_voice"], raw)
        wav = work / f"part_{pi:02d}.wav"
        _wav48(raw, wav, pad_after=PART_GAP)
        dur = ffprobe_duration(wav)
        log(f"voice part {pi + 1}/{len(parts)} {dur:.1f}s ({model})")
        for s in part:
            segs.append(dict(s, part=pi, part_start=cursor, part_dur=dur))
        wavs.append(wav)
        cursor += dur
    voice = work / "voice.wav"
    _concat(wavs, voice)
    total = ffprobe_duration(voice)
    align_words(voice, segs, total)
    return voice, total, segs


def _synth_per_segment(parts, cfg, work, engine):
    wavs, segs, cursor = [], [], 0.0
    n = 0
    for pi, part in enumerate(parts):
        for si, s in enumerate(part):
            raw = work / f"seg_{n:03d}.mp3"
            if engine == "fake":
                raw = work / f"seg_{n:03d}_raw.wav"
                _fake(s["text"], raw)
                words = []
            else:
                words = edge_tts_file(s["text"], cfg, raw)
            gap = 0.22
            if si == len(part) - 1:
                gap = PART_GAP
            if s.get("role") == "card":
                gap = CARD_GAP + 0.25
            wav = work / f"seg_{n:03d}.wav"
            _wav48(raw, wav, pad_after=gap)
            dur = ffprobe_duration(wav)
            # Edge offsets are relative to the raw file; silenceremove trims ~0-50 ms -> close enough
            lead = 0.0
            if words:
                lead = max(0.0, words[0]["start"] - 0.05)
                ws = [{"start": cursor + w["start"] - lead, "end": cursor + w["end"] - lead, "word": w["word"]}
                      for w in words]
            else:
                ws = _even(s["text"], cursor + 0.05, max(0.5, dur - gap - 0.1))
            segs.append(dict(s, part=pi, start=cursor, dur=dur, words=ws))
            wavs.append(wav)
            cursor += dur
            n += 1
    voice = work / "voice.wav"
    _concat(wavs, voice)
    total = ffprobe_duration(voice)
    log(f"voice ({engine}) {total:.1f}s, {n} segments")
    return voice, total, segs


def voice_test(cfg, out_dir: Path):
    """Kon voice bhalo lage shunte: koyekta Gemini + Edge voice e same line."""
    out_dir.mkdir(parents=True, exist_ok=True)
    line = ("Nobody is coming to save you. Not today. Not tomorrow. So get up, "
            "because the version of you that wins is waiting on the other side of this decision.")
    for v in ["Algenib", "Charon", "Orus", "Fenrir", "Alnilam", "Iapetus", "Enceladus", "Rasalgethi",
              "Gacrux", "Sadaltager", "Umbriel", "Schedar"]:
        try:
            raw = out_dir / f"gemini_{v}.wav"
            gemini_tts(line, v, raw)
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-b:a", "128k",
                 str(out_dir / f"gemini_{v}.mp3")])
            raw.unlink()
            log("voice test ok: " + v)
        except Exception as e:
            log(f"voice test {v} failed: {str(e)[:150]}")
    for v in ["en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-AndrewNeural", "en-GB-RyanNeural"]:
        try:
            edge_tts_file(line, cfg, out_dir / f"edge_{v}.mp3", voice=v)
        except Exception as e:
            log(f"edge test {v} failed: {e}")
