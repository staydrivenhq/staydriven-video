"""Caption timing: protiti shobdo voice er thik kokhon bola hocche.

1) faster-whisper voice shune shobdo + shomoy ber kore, script er shobder sathe mil kora hoy.
2) Ja mile na (ba whisper na chole), segulo shudhu voice er KOTHA-BOLAR jaygay (nirob jayga bad diye)
   shobder length onujayi boshano hoy. Tai caption kokhono nirobotar shomoy egiye jay na.
"""
import difflib
import re

import numpy as np

from .util import log


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def _speech_mask(voice_wav):
    """10 ms frame er True/False: ekhane kotha hocche kina."""
    from .voice import _read_mono, pauses
    a = _read_mono(voice_wav)
    n = len(a) // 480
    mask = np.ones(n, dtype=bool)
    for s, e in pauses(a, thresh_db=-40.0, min_len=0.12):
        mask[int(s * 100):int(e * 100)] = False
    return mask


def _spread_on_speech(mask, left, right, lens):
    """lens (char length) onujayi shobd gulo [left, right] er moddhe shudhu kotha-bolar frame e boshay."""
    a, b = int(left * 100), max(int(left * 100) + 1, int(right * 100))
    idx = np.arange(a, min(b, len(mask)))
    voiced = idx[mask[idx]] if len(idx) else idx
    if len(voiced) < len(lens):            # almost no speech found: plain spread
        voiced = idx if len(idx) else np.array([a])
    cum = np.cumsum([0] + lens) / max(1, sum(lens))
    out = []
    for k in range(len(lens)):
        i0 = voiced[min(len(voiced) - 1, int(cum[k] * len(voiced)))]
        i1 = voiced[min(len(voiced) - 1, max(int(cum[k + 1] * len(voiced)) - 1, 0))]
        out.append((i0 / 100.0, max(i1 / 100.0 + 0.01, i0 / 100.0 + 0.08)))
    return out


def _whisper(voice_wav):
    heard = []
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        result, _ = model.transcribe(str(voice_wav), word_timestamps=True, beam_size=1,
                                     condition_on_previous_text=False, vad_filter=True,
                                     vad_parameters={"min_silence_duration_ms": 300})
        for seg in result:
            for w in seg.words or []:
                heard.append((w.start, w.end, w.word.strip()))
    except Exception as e:
        log(f"align: whisper not available ({str(e)[:160]})")
    return heard


def align_words(voice_wav, segs, total):
    script = [(i, w) for i, s in enumerate(segs) for w in s["text"].split()]
    n = len(script)
    mask = _speech_mask(voice_wav)
    heard = _whisper(voice_wav)

    times = [None] * n
    if heard:
        a = [_norm(w) for _, w in script]
        b = [_norm(w) for _, _, w in heard]
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                hs, he, _ = heard[blk.b + k]
                times[blk.a + k] = (hs, he)
        matched = sum(t is not None for t in times)
        log(f"align: whisper matched {matched}/{n} words")
        if matched < n * 0.5:
            log("align: whisper match too low, using speech-activity timing only")
            times = [None] * n
    else:
        log("align: using speech-activity timing")

    # part boundaries keep unmatched words inside their own voice part
    part_of = [segs[i]["part"] for i, _ in script]
    bounds = {}
    for s in segs:
        bounds[s["part"]] = (s["part_start"], s["part_start"] + s["part_dur"])

    k = 0
    while k < n:
        if times[k] is not None:
            k += 1
            continue
        j = k
        while j < n and times[j] is None and part_of[j] == part_of[k]:
            j += 1
        p_start, p_end = bounds[part_of[k]]
        left = times[k - 1][1] if k > 0 and times[k - 1] is not None and part_of[k - 1] == part_of[k] \
            else p_start
        right = times[j][0] if j < n and times[j] is not None and part_of[j] == part_of[k] else p_end
        lens = [len(script[m][1]) + 1 for m in range(k, j)]
        for m, t in zip(range(k, j), _spread_on_speech(mask, left, right, lens)):
            times[m] = t
        k = j

    last = 0.0
    for m in range(n):
        s, e = times[m]
        s = max(s, last)
        times[m] = (s, max(e, s + 0.08))
        last = s

    # quality check: how many caption words start while the voice is silent?
    off = sum(1 for s, _ in times if 0 <= int(s * 100) < len(mask) and
              not mask[max(0, int(s * 100) - 15):int(s * 100) + 16].any())
    log(f"align: {n - off}/{n} caption words start on spoken audio")

    for i, s in enumerate(segs):
        s["words"] = [{"start": times[m][0], "end": times[m][1], "word": script[m][1]}
                      for m in range(n) if script[m][0] == i]
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
