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


def _read_mono(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                       capture_output=True)
    return np.frombuffer(p.stdout, dtype="<f4").astype(np.float32)


def _write_mono(path, a):
    a = np.clip(a, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((a * 32767).astype("<i2").tobytes())


def pauses(a, sr=48000, thresh_db=-42.0, min_len=0.12):
    """Nirob jayga gulo: [(start_sec, end_sec), ...] (10 ms frame)."""
    hop = int(sr * 0.01)
    n = len(a) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    quiet = db < thresh_db
    out, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * 0.01 >= min_len:
                out.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return out


def squeeze_pauses(path, max_pause=0.55, keep=0.40):
    """Gemini voice majhe majhe lomba nirobota dhokay (2-6 s). Oigulo choto kore dey.
    Returns (longest pause before fixing, seconds removed)."""
    a = _read_mono(path)
    sr = 48000
    ps = [(s, e) for s, e in pauses(a) if s > 0.05 and e < len(a) / sr - 0.05]
    longest = max([e - s for s, e in ps], default=0.0)
    keep_parts, last, removed = [], 0, 0.0
    for s, e in ps:
        if e - s <= max_pause:
            continue
        cut_a = int((s + keep / 2) * sr)
        cut_b = int((e - keep / 2) * sr)
        fade = int(0.01 * sr)
        seg = a[last:cut_a].copy()
        if len(seg) > fade:
            seg[-fade:] *= np.linspace(1, 0, fade)
        keep_parts.append(seg)
        removed += (cut_b - cut_a) / sr
        last = cut_b
    tail = a[last:].copy()
    fade = int(0.01 * sr)
    if removed and len(tail) > fade:
        tail[:fade] *= np.linspace(0, 1, fade)
    keep_parts.append(tail)
    out = np.concatenate(keep_parts)
    # trailing dead air (Gemini sometimes adds seconds of silence at the end)
    loud = np.where(np.abs(out) > 10 ** (-42 / 20))[0]
    if len(loud):
        end = min(len(out), loud[-1] + int(0.15 * sr))
        removed += (len(out) - end) / sr
        out = out[:end]
    _write_mono(path, out)
    return longest, removed


def _synth_gemini(parts, cfg, work):
    from .align import align_words
    wavs, segs, cursor = [], [], 0.0
    for pi, part in enumerate(parts):
        raw = work / f"part_{pi:02d}_raw.wav"
        text = " ".join(s["text"] for s in part)
        words = len(text.split())
        wav = work / f"part_{pi:02d}.wav"
        for attempt in range(3):
            model = gemini_tts(text, cfg["gemini_voice"], raw)
            _wav48(raw, wav, pad_after=0.0)
            longest, removed = squeeze_pauses(wav)
            speech = ffprobe_duration(wav)
            # ~2.0-3.3 words/sec is normal. Far shorter = text was cut off; retry.
            if speech >= words / 4.2 or attempt == 2:
                break
            log(f"voice part {pi + 1}: only {speech:.1f}s for {words} words (cut off?), retrying")
        if removed:
            log(f"voice part {pi + 1}: removed {removed:.1f}s of dead air (longest pause was {longest:.1f}s)")
        padded = work / f"part_{pi:02d}_p.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", f"apad=pad_dur={PART_GAP}",
             "-ar", "48000", "-ac", "1", str(padded)])
        wav = padded
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
