"""Protidin notun, research-based script. Format rotate hoy jate channel 'template copy' na lage."""
import random
import re

from .llm import ask, extract_json, log

LONG_FORMATS = {
    "truths": "4 hard truths. Points are labeled 'TRUTH #1' ... 'TRUTH #4'. Each truth stings first, then heals.",
    "rules": "4 rules to live by. Points are labeled 'RULE #1' ... 'RULE #4'. Each rule ends with one concrete action.",
    "story": ("A real, documented comeback story taken ONLY from the research notes, told cinematically, "
              "then 3 lessons. Points are labeled 'LESSON #1' ... 'LESSON #3'. The hook starts inside the "
              "darkest moment of the story."),
    "science": ("What research and real history reveal about the theme, taken ONLY from the research notes, "
                "turned into 3 mindset shifts. Points are labeled 'SHIFT #1' ... 'SHIFT #3'. Explain each "
                "finding in plain words, never invent numbers."),
    "letter": ("A raw, emotional letter spoken to the viewer who is about to give up. Three movements labeled "
               "'PART I', 'PART II', 'PART III' (the pain, the truth, the rise)."),
}

SHORT_STYLES = {
    "hard_truth": "One brutal truth, then the reframe that makes them want to stand up.",
    "mini_story": "A 35-second real story from the research notes with a twist ending and one lesson.",
    "reframe": "Start with what they believe ('You think...'), destroy it, give the new belief.",
    "challenge": "A specific 30-day challenge with a reason it works and a dare at the end.",
    "question": "Open with a question that hurts a little, answer it like a coach who cares.",
}

STYLE_RULES = """
WRITING STYLE (most important):
- Audience: English-speaking viewers in the US, 18-35, who feel stuck and want to change.
- Sound like a real, intense, caring coach speaking out loud. Short sentences. Rhythm. Rule of three.
  Vary sentence length: a long build, then a three-word punch.
- Second person ("you"). Concrete images (the 5 AM alarm, the cold floor, the empty gym, the unread
  messages), not abstract words.
- Retention: every 25-40 seconds add a pattern interrupt (a question, a sudden short line, a twist, an
  open loop like "but the next one is the one that changes everything").
- Never use these AI cliches: "in today's world", "buckle up", "let's dive in", "unleash", "unlock your
  potential", "journey", "game-changer", "embrace", "tapestry", "delve", "testament", "realm".
- No em dashes or en dashes. Use periods and commas.
- Never claim personal experiences ("when I was 19..."), never invent statistics, never put words in a
  real famous person's mouth. Facts about real people/studies must come from the research notes.
- No medical, financial or legal advice. No emojis, no stage directions, no sound cues, no quotes marks
  around the narration.
"""

VISUAL_RULES = """
"visual": a 2-5 word stock-footage search in English that a stock site really has. Cinematic and moody:
silhouettes, slow motion, athletes training, boxer, sprinter, rain on window, storm clouds, mountain summit,
ocean waves crashing, empty road at dawn, city lights at night, man walking alone, hands writing journal,
chess pieces, clock ticking, fire, waterfall. Match the line's emotion. No brands, no famous people, no text.
Do not repeat the exact same search more than twice.
"visual2": a DIFFERENT 2-5 word search for the same moment (another subject or angle), so long lines
don't sit on one clip.
"impact": ONE word copied exactly from that segment's text that should hit hardest on screen (or "").
Use impact on about one third of segments only.
"lower_third": documentary label like "OHIO, 1998" or "STANFORD STUDY, 1972" ONLY when the line
mentions a real place/year/study from the research notes; otherwise "". At most 4 per script.
"""


def research(cfg, theme):
    if not cfg.get("use_research"):
        return ""
    prompt = (f"Research for a motivational video about: {theme}.\n"
              "Find 3 lesser-known but verifiable items: a real comeback story (person, year, what happened, "
              "numbers), a real study or experiment with its key finding, and one surprising historical fact. "
              "For each give names, dates and numbers exactly as reported, plus one line on why it matters. "
              "Only include things you can verify with search. Plain text, under 350 words.")
    try:
        notes = ask(cfg, prompt, grounding=True, temperature=0.4)
        log(f"research notes {len(notes.split())} words")
        return notes.strip()
    except Exception as e:
        log(f"research skipped: {e}")
        return ""


def _pick(options, recent):
    fresh = [o for o in options if o not in recent[-max(1, len(options) - 2):]]
    return random.choice(fresh or list(options))


def _words(segs):
    return sum(len(s["text"].split()) for s in segs)


def _clean_text(t):
    t = re.sub(r"[—–]", ", ", str(t))
    t = re.sub(r"\s+,", ",", t)
    return re.sub(r"\s+", " ", t).strip()


def _get(d, *names, default=None):
    """First key that exists (models sometimes rename keys: close/outro/ending...)."""
    for n in names:
        if isinstance(d, dict) and d.get(n):
            return d[n]
    return default


def _normalize_long(d):
    """Repairs a long script whose shape is slightly off, so one missing key does not waste a run."""
    d["hook"] = _get(d, "hook", "intro", "opening", default=[])
    d["close"] = _get(d, "close", "outro", "ending", "conclusion", "closing", default=[])
    pts = _get(d, "points", "sections", "body", "parts", default=[])
    fixed = []
    for i, p in enumerate(pts if isinstance(pts, list) else []):
        if isinstance(p, dict):
            segs = _get(p, "segments", "lines", "content", default=[])
            fixed.append({"label": str(_get(p, "label", default=f"PART {i + 1}")),
                          "heading": str(_get(p, "heading", "title", default="")),
                          "segments": segs})
    d["points"] = fixed
    if not d["hook"] and fixed and len(fixed[0]["segments"]) > 3:
        d["hook"], fixed[0]["segments"] = fixed[0]["segments"][:2], fixed[0]["segments"][2:]
    if not d["close"] and fixed and len(fixed[-1]["segments"]) > 3:
        d["close"], fixed[-1]["segments"] = fixed[-1]["segments"][-2:], fixed[-1]["segments"][:-2]
    for p in fixed:
        if not p["heading"]:
            first = _clean_text(p["segments"][0]["text"] if p["segments"] and isinstance(p["segments"][0], dict)
                                else (p["segments"][0] if p["segments"] else ""))
            p["heading"] = " ".join(first.split()[:5])
    for k in ("title", "description", "thumbnail_text", "thumbnail_scene", "comment"):
        d.setdefault(k, "")
    d["thumbnail_text"] = d["thumbnail_text"] or " ".join(str(d["title"]).upper().split()[:3])
    d.setdefault("tags", [])
    return d


def _fix_segments(segs):
    out = []
    for s in segs or []:
        if isinstance(s, str):                    # plain sentence instead of an object
            s = {"text": s}
        if not isinstance(s, dict):
            continue
        text = _clean_text(s.get("text", "") or s.get("line", "") or s.get("narration", ""))
        if not text:
            continue
        imp = str(s.get("impact") or "").strip()
        if imp and imp.lower() not in text.lower():
            imp = ""
        vis = str(s.get("visual") or "cinematic silhouette sunrise")
        out.append({"text": text, "visual": vis, "visual2": str(s.get("visual2") or vis),
                    "impact": imp, "lower_third": _clean_text(s.get("lower_third") or "")[:40]})
    return out


def write_long(cfg, history):
    theme = _pick(cfg["themes"], [p.get("theme") for p in history["posts"]])
    fmt = _pick(list(LONG_FORMATS), history.get("long_formats", []))
    notes = research(cfg, theme)
    if fmt in ("story", "science") and len(notes) < 200:
        fmt = random.choice(["truths", "rules", "letter"])
    recent = "\n".join("- " + p.get("title", "") for p in history["posts"][-80:]) or "- none"
    lo, hi = cfg["long_words"]
    prompt = f"""You are the head writer of "{cfg['channel_name']}", a premium cinematic motivation channel.
Today's theme: {theme}
Format: {LONG_FORMATS[fmt]}

Research notes (the ONLY allowed source of real names, dates, numbers):
{notes or '(none: do not mention any real person or study)'}

Recent titles on the channel. Today's angle, title and lines must be clearly different:
{recent}
{STYLE_RULES}
STRUCTURE:
- "hook": 3-5 segments, about 20-30 seconds. Start mid-tension with the single most gripping line of the
  whole video. Promise what they will get if they stay. End the hook with an open loop.
- "points": the format's points. Each has 5-9 segments. The first segment of each point explains the
  heading; include one real example from the notes where it fits.
- "close": 4-6 segments. Emotional peak, then: "If this hit you, subscribe to {cfg['channel_name']}. New one
  every day." as the very last segment.
- Total spoken words across hook, all segments and close: {lo}-{hi}.
{VISUAL_RULES}
METADATA:
- "title": max 60 characters, curiosity + specific promise, honest to the content, Title Case, no emojis,
  no ALL CAPS sentence.
- "thumbnail_text": 2-4 punchy words that ADD to the title (do not repeat it), wrap the one most emotional
  word in asterisks, e.g. "STOP *WAITING*".
- "thumbnail_scene": one cinematic photo description for the thumbnail background (one lone figure,
  dramatic light, strong emotion, empty space on the left for text). No text, no real people.
- "description": 2 short paragraphs, first sentence restates the promise with the main keyword.
- "tags": 10-14 search phrases.
- "comment": a question the channel will post as the first comment to start discussion.

Return ONLY JSON:
{{"title": "", "thumbnail_text": "", "thumbnail_scene": "", "description": "", "tags": [],
  "comment": "",
  "hook": [{{"text": "", "visual": "", "visual2": "", "impact": "", "lower_third": ""}}],
  "points": [{{"label": "", "heading": "3-6 words", "segments": [{{"text": "", "visual": "", "visual2": "", "impact": "", "lower_third": ""}}]}}],
  "close": [{{"text": "", "visual": "", "visual2": "", "impact": "", "lower_third": ""}}]}}
"""
    for attempt in range(4):
        try:
            d = _normalize_long(extract_json(ask(cfg, prompt, json_mode=True)))
            d["hook"] = _fix_segments(d["hook"])
            d["close"] = _fix_segments(d["close"])
            for p in d["points"]:
                p["segments"] = _fix_segments(p["segments"])
                p["heading"] = _clean_text(p["heading"])
                p["label"] = _clean_text(p["label"]).upper()
            total = _words(d["hook"]) + _words(d["close"]) + sum(_words(p["segments"]) for p in d["points"])
            need = lo * (0.85 if attempt < 2 else 0.6)        # later tries: a shorter video beats none
            ok = (total >= need and len(d["points"]) >= 3 and d["hook"] and d["close"]
                  and all(p["segments"] for p in d["points"]))
            if ok:
                d.update(theme=theme, format=fmt, research=notes, words=total)
                log(f"long | {fmt} | {theme} | {total} words | {d['title']}")
                return d
            log(f"long attempt {attempt + 1}: {total} words, {len(d['points'])} points, "
                f"hook {bool(d['hook'])}, close {bool(d['close'])}: asking again")
            prompt += (f"\n\nYour last answer had {total} words or a broken structure. Fix it. Hit {lo}-{hi} words. "
                       "It MUST contain the keys hook, points (at least 3) and close.")
        except Exception as e:
            log(f"long attempt {attempt + 1} failed: {e}")
    raise RuntimeError("Could not write the long script")


def write_short(cfg, history):
    theme = _pick(cfg["themes"], [p.get("theme") for p in history["posts"][-6:]])
    style = _pick(list(SHORT_STYLES), history.get("short_styles", []))
    notes = research(cfg, theme) if style == "mini_story" else ""
    if style == "mini_story" and len(notes) < 200:
        style = "hard_truth"
    recent = "\n".join("- " + p.get("title", "") for p in history["posts"][-80:]) or "- none"
    lo, hi = cfg["short_words"]
    prompt = f"""You write vertical Shorts/Reels for "{cfg['channel_name']}", a premium cinematic motivation channel.
Theme: {theme}
Style: {SHORT_STYLES[style]}
Research notes (only allowed source of real names, dates, numbers):
{notes or '(none: do not mention any real person or study)'}
Recent titles (be clearly different):
{recent}
{STYLE_RULES}
SHORT RULES:
- {lo}-{hi} spoken words in 7-11 segments. Every segment is 1 short sentence.
- Segment 1 is the hook: under 9 words, stops the scroll in the first second.
- Build to a peak. The LAST line must flow naturally back into the FIRST line so the video loops.
- No "subscribe" or "follow" line inside the narration.
{VISUAL_RULES}
- "hook_text": the on-screen hook shown at second 0, max 6 words (can differ slightly from the spoken hook).
- "title": max 55 characters, curiosity, honest.
- "caption": 1-2 lines for Instagram/Facebook, ending with a question.
- "comment": a question for the first comment.

Return ONLY JSON:
{{"title": "", "hook_text": "", "caption": "", "comment": "", "tags": [],
  "segments": [{{"text": "", "visual": "", "visual2": "", "impact": "", "lower_third": ""}}]}}
"""
    for attempt in range(4):
        try:
            d = extract_json(ask(cfg, prompt, json_mode=True))
            d["segments"] = _fix_segments(_get(d, "segments", "lines", "script", default=[]))
            for k in ("title", "caption", "comment", "hook_text"):
                d.setdefault(k, "")
            d["caption"] = d["caption"] or d["title"]
            total = _words(d["segments"])
            if lo * (0.8 if attempt < 2 else 0.6) <= total <= hi * 1.4 and len(d["segments"]) >= 5:
                d.update(theme=theme, format=style, research=notes, words=total)
                log(f"short | {style} | {theme} | {total} words | {d['title']}")
                return d
            prompt += f"\n\nYour last answer had {total} words. Hit {lo}-{hi}."
        except Exception as e:
            log(f"short attempt {attempt + 1} failed: {e}")
    raise RuntimeError("Could not write the short script")


def to_timeline_parts(kind, d):
    """Script -> voice 'parts' (ek ek TTS call) and flat segment list with roles."""
    if kind == "short":
        segs = [dict(s, role="line") for s in d["segments"]]
        segs[0]["role"] = "hook"
        return [segs]
    parts = [[dict(s, role="hook") for s in d["hook"]]]
    for i, p in enumerate(d["points"]):
        nums = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six"}
        spoken_label = re.sub(r"#\s*(\d+)", lambda m: "number " + nums.get(m.group(1), m.group(1)),
                              p["label"].title())
        spoken_label = spoken_label.replace("Part Iii", "Part three").replace("Part Ii", "Part two") \
                                   .replace("Part I", "Part one")
        card = {"text": f"{spoken_label}. {p['heading']}.", "visual": p["segments"][0]["visual"],
                "impact": "", "role": "card", "label": p["label"], "heading": p["heading"], "chapter": i + 1}
        parts.append([card] + [dict(s, role="line") for s in p["segments"]])
    parts.append([dict(s, role="close") for s in d["close"]])
    return parts
