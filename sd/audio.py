"""Original cinematic score + sound effects (100% nijer banano, kono copyright nai) ar final mix plan.
music/ folder e nijer royalty-free track rakhle setai priority pabe."""
import random
import wave

import numpy as np
from scipy.signal import butter, lfilter

from .util import ROOT, log

SR = 48000
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _lp(x, f, order=2):
    b, a = butter(order, f / (SR / 2), btype="low")
    return lfilter(b, a, x, axis=0)


def _hp(x, f, order=2):
    b, a = butter(order, f / (SR / 2), btype="high")
    return lfilter(b, a, x, axis=0)


def _bp(x, lo, hi):
    b, a = butter(2, [lo / (SR / 2), hi / (SR / 2)], btype="band")
    return lfilter(b, a, x, axis=0)


def write_wav(path, stereo):
    stereo = np.clip(stereo, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype("<i2").tobytes())


def _add(buf, start_s, sig):
    i = int(start_s * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    if i < 0:
        sig, i = sig[-i:], 0
    n = min(len(sig), len(buf) - i)
    buf[i:i + n] += sig[:n]


def _env(n, attack, release):
    e = np.ones(n, dtype=np.float32)
    a, r = int(attack * SR), int(release * SR)
    if a:
        e[:a] = np.linspace(0, 1, a) ** 1.5
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 1.5
    return e


# ------------------------------------------------------------------ score
def make_score(total, intensity_at, path, seed, bpm=72):
    """total: seconds. intensity_at(t) -> 0..3 (story er mood onujayi build up)."""
    rnd = random.Random(seed)
    root = rnd.choice([57, 55, 52, 50, 53])            # A, G, E, D, F minor (MIDI, octave 3)
    progs = [[0, 8, 3, 10], [0, 5, 8, 7], [0, 8, 10, 7], [0, 3, 8, 10]]
    prog = rnd.choice(progs)                            # i VI III VII etc. (minor key)
    beat = 60.0 / bpm
    chord_len = beat * 8                                # 2 bars per chord
    n = int((total + 3) * SR)
    L = np.zeros(n, np.float32)
    R = np.zeros(n, np.float32)
    t_chord = 0.0
    ci = 0
    log(f"score: root {root} prog {prog} bpm {bpm}")
    while t_chord < total + 2:
        deg = prog[ci % len(prog)]
        lvl = intensity_at(t_chord + chord_len / 2)
        m = root + deg
        triad = [m, m + (4 if deg in (8, 3, 10, 5) else 3), m + 7]
        seg_n = int((chord_len + 1.5) * SR)
        tt = np.arange(seg_n) / SR
        env = _env(seg_n, 1.2, 1.6)
        # pad: soft detuned partials (warm, dark)
        padL = np.zeros(seg_n, np.float32)
        padR = np.zeros(seg_n, np.float32)
        for note in triad + [m + 12]:
            f = hz(note)
            for k, amp in ((1, 1.0), (2, 0.35), (3, 0.16), (4, 0.07)):
                padL += amp * np.sin(2 * np.pi * f * k * 0.998 * tt + rnd.random() * 6)
                padR += amp * np.sin(2 * np.pi * f * k * 1.002 * tt + rnd.random() * 6)
        pad_gain = 0.035 + 0.012 * lvl
        _add(L, t_chord, padL * env * pad_gain)
        _add(R, t_chord, padR * env * pad_gain)
        # sub drone
        sub = np.sin(2 * np.pi * hz(m - 12) * tt) * env * (0.05 + 0.02 * lvl)
        _add(L, t_chord, sub)
        _add(R, t_chord, sub)
        # piano-like arpeggio from intensity 1
        if lvl >= 1:
            arp = [triad[0] + 12, triad[1] + 12, triad[2] + 12, triad[1] + 12]
            step = beat / (2 if lvl >= 2 else 1)
            k = 0
            t = 0.0
            while t < chord_len - 0.05:
                f = hz(arp[k % 4])
                nn = int(1.8 * SR)
                ts = np.arange(nn) / SR
                tone = (np.sin(2 * np.pi * f * ts) + 0.4 * np.sin(4 * np.pi * f * ts) +
                        0.15 * np.sin(6 * np.pi * f * ts)) * np.exp(-ts * 3.2)
                tone[:120] *= np.linspace(0, 1, 120)
                g = 0.05 if lvl < 2 else 0.06
                pan = 0.35 + 0.3 * ((k % 4) / 3)
                _add(L, t_chord + t, tone * g * (1 - pan) * 1.4)
                _add(R, t_chord + t, tone * g * pan * 1.4)
                t += step
                k += 1
        # heartbeat drum from intensity 2
        if lvl >= 2:
            for b in range(8):
                if b % 2 == 0:
                    nn = int(0.6 * SR)
                    ts = np.arange(nn) / SR
                    f = 48 + 40 * np.exp(-ts * 30)
                    kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-ts * 7) * 0.22
                    _add(L, t_chord + b * beat, kick)
                    _add(R, t_chord + b * beat, kick)
        # high strings swell at the peak
        if lvl >= 3:
            sw = np.zeros(seg_n, np.float32)
            for note in (triad[0] + 24, triad[2] + 24):
                f = hz(note)
                vib = 0.004 * np.sin(2 * np.pi * 5.2 * tt)
                sw += np.sin(2 * np.pi * f * tt * (1 + vib)) + 0.3 * np.sin(4 * np.pi * f * tt)
            _add(L, t_chord, sw * _env(seg_n, 2.5, 1.5) * 0.02)
            _add(R, t_chord, sw * _env(seg_n, 2.5, 1.5) * 0.02)
        t_chord += chord_len
        ci += 1
    st = np.stack([L, R], 1)
    st = _lp(st, 6500)
    # simple stereo "hall": a few delayed, filtered copies
    rev = np.zeros_like(st)
    for d, g in ((0.031, 0.28), (0.047, 0.22), (0.071, 0.18), (0.113, 0.12), (0.173, 0.08)):
        k = int(d * SR)
        rev[k:, 0] += st[:-k, 1] * g
        rev[k:, 1] += st[:-k, 0] * g
    st = st + _lp(rev, 3500)
    st = st[: int((total + 1.0) * SR)]
    fade = int(2.5 * SR)
    st[-fade:] *= np.linspace(1, 0, fade)[:, None]
    st[: int(1.0 * SR)] *= np.linspace(0, 1, int(1.0 * SR))[:, None]
    peak = np.max(np.abs(st)) or 1
    write_wav(path, st / peak * 0.8)
    return path


# ------------------------------------------------------------------ sfx
def _noise(nn, seed):
    return np.random.default_rng(seed).standard_normal(nn).astype(np.float32)


def sfx_boom(seed=1):
    nn = int(1.6 * SR)
    ts = np.arange(nn) / SR
    f = 38 + 55 * np.exp(-ts * 12)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-ts * 2.6)
    thump = _lp(_noise(nn, seed), 180) * np.exp(-ts * 18) * 2.5
    s = (body + thump) * 0.55
    return np.stack([s, s], 1)


def sfx_whoosh(seed=2, dur=0.7):
    nn = int(dur * SR)
    x = np.linspace(0, 1, nn)
    env = np.sin(np.pi * x) ** 2
    nz = _noise(nn, seed)
    lo, hi = _bp(nz, 300, 1200), _bp(nz, 1500, 6000)
    s = (lo * (1 - x) + hi * x) * env * 0.9
    pan = x
    return np.stack([s * (1 - pan * 0.6), s * (0.4 + pan * 0.6)], 1)


def sfx_riser(seed=3, dur=1.6):
    nn = int(dur * SR)
    x = np.linspace(0, 1, nn)
    nz = _hp(_noise(nn, seed), 900) * x ** 2.2 * 0.35
    ts = np.arange(nn) / SR
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * x ** 2) / SR) * x ** 3 * 0.12
    s = nz + tone
    s[-200:] *= np.linspace(1, 0, 200)
    return np.stack([s, s], 1)


def sfx_tick(seed=4):
    nn = int(0.08 * SR)
    ts = np.arange(nn) / SR
    s = (np.sin(2 * np.pi * 1800 * ts) * 0.4 + _hp(_noise(nn, seed), 3000) * 0.3) * np.exp(-ts * 70)
    return np.stack([s, s], 1)


def make_sfx(total, events, path):
    """events: [(kind, time)]  kind in boom/whoosh/riser/tick"""
    buf = np.zeros((int((total + 2) * SR), 2), np.float32)
    lib = {"boom": (sfx_boom(), 0.0, 0.55), "whoosh": (sfx_whoosh(), -0.35, 0.45),
           "riser": (sfx_riser(), -1.6, 0.5), "tick": (sfx_tick(), 0.0, 0.25)}
    for kind, t in events:
        sig, off, g = lib[kind]
        i = int((t + off) * SR)
        if i < 0:
            sig, i = sig[-i:], 0
        n = min(len(sig), len(buf) - i)
        if n > 0:
            buf[i:i + n] += sig[:n] * g
    write_wav(path, buf[: int((total + 1.0) * SR)])
    return path


def user_tracks():
    return [p for p in (ROOT / "music").glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg")]
