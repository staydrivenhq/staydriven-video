"""Gemini voice word-timing dey na -> faster-whisper diye shuney protiti shobder shomoy ber kori,
tarpor script er shobder sathe mil kori (caption ekdom voice er sathe sync)."""
import difflib
import re

from .util import log


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def align_words(voice_wav, segs, total):
    script = []                       # (seg_index, original_word)
    for i, s in enumerate(segs):
        for w in s["text"].split():
            script.append((i, w))
    heard = []
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        result, _ = model.transcribe(str(voice_wav), word_timestamps=True, beam_size=1,
                                     condition_on_previous_text=False, vad_filter=False)
        for seg in result:
            for w in seg.words or []:
                heard.append((w.start, w.end, w.word.strip()))
        log(f"align: whisper heard {len(heard)} words, script has {len(script)}")
    except Exception as e:
        log(f"align: whisper unavailable ({e}), spreading words by part length")

    times = [None] * len(script)
    if heard:
        a = [_norm(w) for _, w in script]
        b = [_norm(w) for _, _, w in heard]
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                hs, he, _ = heard[blk.b + k]
                times[blk.a + k] = (hs, he)
        matched = sum(t is not None for t in times)
        log(f"align: matched {matched}/{len(script)} words")

    # anchors for each voice part boundary so unmatched words stay inside their part
    parts = {}
    for i, s in enumerate(segs):
        p = parts.setdefault(s["part"], [s["part_start"], s["part_start"] + s["part_dur"], []])
        p[2].append(i)

    # fill gaps by interpolation (by character length) between known neighbours
    n = len(script)
    idx = 0
    while idx < n:
        if times[idx] is not None:
            idx += 1
            continue
        j = idx
        while j < n and times[j] is None:
            j += 1
        seg_part = segs[script[idx][0]]["part"]
        p_start, p_end, _ = parts[seg_part]
        left = times[idx - 1][1] if idx > 0 and times[idx - 1] is not None and \
            segs[script[idx - 1][0]]["part"] == seg_part else p_start + 0.05
        right = times[j][0] if j < n and segs[script[j][0]]["part"] == seg_part else p_end - 0.45
        right = max(right, left + 0.2 * (j - idx))
        lens = [len(script[k][1]) + 2 for k in range(idx, j)]
        tot = sum(lens)
        t = left
        for k, L in zip(range(idx, j), lens):
            d = (right - left) * L / tot
            times[k] = (t, t + d * 0.9)
            t += d
        idx = j

    # monotonic clean-up
    last = 0.0
    for k in range(n):
        s, e = times[k]
        s = max(s, last)
        e = max(e, s + 0.08)
        times[k] = (s, e)
        last = s

    for i, s in enumerate(segs):
        s["words"] = [{"start": times[k][0], "end": times[k][1], "word": script[k][1]}
                      for k in range(n) if script[k][0] == i]
    # segment boundaries: from first word (minus lead-in) to next segment's start
    for i, s in enumerate(segs):
        st = s["words"][0]["start"] - 0.08 if s["words"] else s["part_start"]
        if i == 0:
            st = 0.0
        elif s["part"] != segs[i - 1]["part"]:
            st = s["part_start"]
        s["start"] = max(0.0, st)
    for i, s in enumerate(segs):
        end = segs[i + 1]["start"] if i + 1 < len(segs) else total
        s["dur"] = max(0.3, end - s["start"])
