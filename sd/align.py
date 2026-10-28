"""Caption timing, direct from the voice audio (no speech-recognition guessing).

1) Each voice part is one TTS recording of several sentences. Sentences end with a real pause,
   so the part is split at the pauses that best match where each sentence should end
   (dynamic programming over the detected pauses). Every caption sentence therefore starts
   exactly when its spoken sentence starts: errors can never build up across the video.
2) Inside one sentence, words are spread only over the frames where the voice is speaking,
   in proportion to word length.
"""
import numpy as np

from .util import log


def speech_mask(voice_wav):
    """True for each 10 ms frame where the voice is speaking."""
    from .voice import _read_mono, pauses
    a = _read_mono(voice_wav)
    n = len(a) // 480
    mask = np.ones(n, dtype=bool)
    for s, e in pauses(a, thresh_db=-40.0, min_len=0.08):
        mask[int(s * 100):int(e * 100)] = False
    return mask


def _quiet_runs(mask, a, b):
    """Silent runs strictly inside frames [a, b): list of (start_frame, end_frame)."""
    runs, i = [], a
    while i < b:
        if not mask[i]:
            j = i
            while j < b and not mask[j]:
                j += 1
            if i > a and j < b:                 # ignore silence touching the edges
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _voiced_time_at(mask, a, b, frac):
    """Frame where `frac` of the voiced frames in [a, b) have passed."""
    idx = np.arange(a, b)
    v = idx[mask[a:b]]
    if not len(v):
        return a + frac * (b - a)
    return float(v[min(len(v) - 1, int(frac * len(v)))])


def _split_part(mask, a, b, texts):
    """Frame boundaries for len(texts) sentences inside part frames [a, b)."""
    k = len(texts)
    if k == 1:
        return [a, b]
    lens = np.array([len(t) + 2 for t in texts], dtype=float)
    cum = np.cumsum(lens)[:-1] / lens.sum()
    expected = [_voiced_time_at(mask, a, b, f) for f in cum]        # where each boundary should be
    runs = _quiet_runs(mask, a, b)
    if len(runs) < k - 1:
        log(f"align: only {len(runs)} pauses for {k} sentences, using proportional split")
        return [a] + [int(e) for e in expected] + [b]
    mids = [(s + e) / 2 for s, e in runs]
    lens_r = [(e - s) / 100.0 for s, e in runs]
    span = max(1.0, (b - a))
    INF = 1e18
    P = len(runs)
    # dp[i][j]: best cost placing boundary i at pause j
    dp = np.full((k - 1, P), INF)
    back = np.zeros((k - 1, P), dtype=int)

    def cost(i, j):
        dist = abs(mids[j] - expected[i]) / span * 10.0          # far from expected = bad
        return dist - 1.5 * min(lens_r[j], 0.8)                   # long pause = sentence end = good

    for j in range(P):
        dp[0][j] = cost(0, j)
    for i in range(1, k - 1):
        best, arg = INF, -1
        for j in range(P):
            if j - 1 >= 0 and dp[i - 1][j - 1] < best:
                best, arg = dp[i - 1][j - 1], j - 1
            if arg >= 0:
                dp[i][j] = best + cost(i, j)
                back[i][j] = arg
    j = int(np.argmin(dp[k - 2]))
    picks = [j]
    for i in range(k - 2, 0, -1):
        j = int(back[i][j])
        picks.append(j)
    picks.reverse()
    cuts = []
    for j in picks:
        s, e = runs[j]
        cuts.append(int(e) - 3)                 # next sentence starts just before speech returns
    return [a] + cuts + [b]


def _spread(mask, a, b, words):
    """Word (start, end) seconds inside frames [a, b), only on speaking frames."""
    lens = [len(w) + 1 for w in words]
    idx = np.arange(a, max(a + 1, b))
    idx = idx[idx < len(mask)]
    voiced = idx[mask[idx]] if len(idx) else idx
    if len(voiced) < len(words):
        voiced = idx if len(idx) else np.array([a])
    cum = np.cumsum([0] + lens) / max(1, sum(lens))
    out = []
    for k in range(len(words)):
        i0 = voiced[min(len(voiced) - 1, int(cum[k] * len(voiced)))]
        i1 = voiced[min(len(voiced) - 1, max(int(cum[k + 1] * len(voiced)) - 1, 0))]
        out.append((i0 / 100.0, max(i1 / 100.0 + 0.01, i0 / 100.0 + 0.08)))
    return out


def align_words(voice_wav, segs, total):
    mask = speech_mask(voice_wav)
    n_frames = len(mask)
    parts = {}
    for i, s in enumerate(segs):
        parts.setdefault(s["part"], []).append(i)
    for p, ids in parts.items():
        s0 = segs[ids[0]]
        a = int(s0["part_start"] * 100)
        b = min(n_frames, int((s0["part_start"] + s0["part_dur"]) * 100))
        # trim the part to its speech (skip the pause padding at its end)
        voiced = np.where(mask[a:b])[0]
        sa, sb = (a + voiced[0], a + voiced[-1] + 1) if len(voiced) else (a, b)
        bounds = _split_part(mask, sa, sb, [segs[i]["text"] for i in ids])
        for k, i in enumerate(ids):
            fa, fb = bounds[k], bounds[k + 1]
            words = segs[i]["text"].split()
            times = _spread(mask, fa, fb, words)
            segs[i]["words"] = [{"start": t0, "end": t1, "word": w} for (t0, t1), w in zip(times, words)]
            segs[i]["start"] = (a if k == 0 else fa) / 100.0
        if len(ids) > 1:
            log(f"align: part {p + 1}: {len(ids)} sentences placed on the voice")
    segs[0]["start"] = 0.0
    for i, s in enumerate(segs):
        end = segs[i + 1]["start"] if i + 1 < len(segs) else total
        s["dur"] = max(0.3, end - s["start"])
    check(segs, mask, total)


def check(segs, mask, total):
    """Returns the worst stretch of speech with no caption change (seconds)."""
    starts = sorted(w["start"] for s in segs for w in s["words"])
    sp = np.where(mask)[0]
    if not len(sp) or not starts:
        return 0.0
    edges = [sp[0] / 100.0] + starts + [sp[-1] / 100.0]
    worst = 0.0
    for a, b in zip(edges, edges[1:]):
        ia, ib = int(max(0, a) * 100), int(max(0, b) * 100)
        if ib > ia:
            worst = max(worst, mask[ia:ib].sum() / 100.0)
    last_word = starts[-1]
    log(f"align: check | longest speech without a caption change {worst:.1f}s | "
        f"last caption word {last_word:.1f}s, voice ends {sp[-1] / 100.0:.1f}s")
    return worst
