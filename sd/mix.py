"""Final audio mix, done in numpy (no ffmpeg ducking/loudnorm filters, which sometimes dropped
whole seconds of audio). Also checks the finished video: wherever the voice speaks, the final
audio must not be silent."""
import json
import re
import subprocess
import wave

import numpy as np

from .util import log

SR = 48000


def _read(path, channels, seconds=None, loop=False):
    cmd = ["ffmpeg", "-v", "error"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(path)]
    if seconds:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-map", "0:a:0", "-f", "f32le", "-ac", str(channels), "-ar", str(SR), "-"]
    p = subprocess.run(cmd, capture_output=True)
    a = np.frombuffer(p.stdout, dtype="<f4").astype(np.float32)
    a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    return a.reshape(-1, channels) if channels > 1 else a


def _fit(a, n):
    if len(a) >= n:
        return a[:n]
    pad = np.zeros((n - len(a),) + a.shape[1:], dtype=np.float32)
    return np.concatenate([a, pad])


def _envelope(x, attack=0.015, release=0.45):
    """Smooth level follower (per 10 ms) for ducking the music under the voice."""
    hop = SR // 100
    n = len(x) // hop + 1
    x = _fit(x, n * hop)
    rms = np.sqrt((x.reshape(n, hop) ** 2).mean(1) + 1e-12)
    env = np.zeros(n, dtype=np.float32)
    a_up, a_dn = np.exp(-0.01 / attack), np.exp(-0.01 / release)
    e = 0.0
    for i, v in enumerate(rms):
        e = a_up * e + (1 - a_up) * v if v > e else a_dn * e + (1 - a_dn) * v
        env[i] = e
    return np.repeat(env, hop)


def _loudness(path):
    """Integrated loudness (LUFS) measured by ffmpeg's ebur128 (measurement only, no processing)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


def _write(path, st):
    st = np.clip(np.nan_to_num(st), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())


def speaking(voice, hop=SR // 10, db=-38.0):
    """True for each 100 ms window where the voice is speaking."""
    n = len(voice) // hop
    rms = np.sqrt((voice[: n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    return 20 * np.log10(rms) > db


def silent_holes(mix_mono, voice, min_len=0.3):
    """Stretches (seconds) where the voice speaks but the mix is (almost) silent."""
    hop = SR // 10
    sp = speaking(voice, hop)
    n = min(len(sp), len(mix_mono) // hop)
    rms = np.sqrt((mix_mono[: n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    bad = sp[:n] & (20 * np.log10(rms) < -45)
    holes, i = [], 0
    while i < n:
        if bad[i]:
            j = i
            while j < n and bad[j]:
                j += 1
            if (j - i) * 0.1 >= min_len:
                holes.append((round(i * 0.1, 1), round(j * 0.1, 1)))
            i = j
        else:
            i += 1
    return holes


def build(voice_path, music, sfx_path, end, cfg, out_path, user_track=False):
    n = int(end * SR)
    v = _fit(_read(voice_path, 1), n)
    music_a = _fit(_read(music, 2, seconds=end + 1, loop=user_track), n)
    st = np.stack([v, v], 1)

    # music: overall level, ducked under the voice, faded out at the end
    vol = cfg.get("music_volume", 0.16) * 2.2
    env = _fit(_envelope(v), n)
    duck = 1.0 - 0.72 * np.clip(env / 0.05, 0, 1)            # voice on = music ~ -11 dB
    fade = np.ones(n, dtype=np.float32)
    k = min(n, int(2.5 * SR))
    fade[-k:] = np.linspace(1, 0, k)
    st += music_a * (vol * duck * fade)[:, None]
    if sfx_path:
        st += _fit(_read(sfx_path, 2), n) * 0.9

    # loudness to about -14 LUFS (YouTube's level), then a soft limiter so peaks never clip
    tmp = out_path.with_suffix(".pre.wav")
    _write(tmp, st / max(1.0, float(np.abs(st).max())))
    pre_scale = 1.0 / max(1.0, float(np.abs(st).max()))
    lufs = _loudness(tmp)
    gain = 10 ** ((-14.0 - lufs) / 20) * pre_scale if lufs is not None and lufs > -70 else pre_scale
    st *= min(gain, 12.0)
    knee = 0.85
    over = np.abs(st) > knee
    st[over] = np.sign(st[over]) * (knee + (1 - knee) * np.tanh((np.abs(st[over]) - knee) / (1 - knee)))
    _write(out_path, st)
    tmp.unlink(missing_ok=True)

    holes = silent_holes(st.mean(1), v)
    log(f"mix: {end:.1f}s, loudness was {lufs if lufs is not None else 'n/a'} LUFS, "
        f"silent holes while speaking: {holes or 'none'}")
    if holes:
        raise RuntimeError(f"audio mix has silent holes at {holes}")
    return out_path


def verify_video(video, voice_path):
    """Decode the finished video's audio and make sure the voice is really there everywhere."""
    final = _read(video, 1)
    v = _read(voice_path, 1)
    holes = silent_holes(final, v)
    if holes:
        raise RuntimeError(f"final video audio is silent at {holes} while the voice speaks")
    log("check: final video audio follows the voice the whole way")
