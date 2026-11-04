"""Facebook motivational image posts (quote cards) in the Stay Driven signature style.

The look is the same on every post so people recognise the page before they read the name:
  - big condensed CAPS (Anton) mixed with an elegant serif italic (DM Serif Display)
  - ONE key word framed in the gold rounded box from the "HQ" logo
  - a numbered series ("No. 027") top right, logo top left
  - a gold-ruled footer with the handle
Two colourways with the same layout: Night (black) and Paper (warm cream)."""
import os
import random
import re
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from .llm import ask, extract_json, log
from .util import ROOT, font_path

W, H = 1080, 1350
M = 92                                   # side margin
GOLD = (245, 196, 58)

THEMES = {
    "night": {"bg": (12, 12, 14), "big": (246, 244, 238), "small": (182, 178, 170), "rule": GOLD,
              "meta": (150, 146, 138), "grain": 7},
    "paper": {"bg": (237, 231, 218), "big": (16, 16, 18), "small": (88, 84, 78), "rule": (196, 150, 30),
              "meta": (110, 104, 96), "grain": 9},
}

STYLES = {
    "quote": "One original, quotable line (8-20 words) that hits hard and is easy to screenshot and share.",
    "truth": "A hard truth in 2 short sentences (max 22 words): the first stings, the second lifts.",
    "reminder": "A daily reminder that starts with 'Reminder:' (max 20 words), calm but firm.",
    "question": "A sharp question to the reader (max 16 words) that makes them stop and think about their life.",
    "rule": "One life rule that starts with 'Rule:' (max 16 words), concrete and actionable.",
}

# fonts the design needs (free Google Fonts, downloaded once per run if missing)
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = {"serif": ("DMSerifDisplay-Italic.ttf", "dmserifdisplay/DMSerifDisplay-Italic.ttf"),
         "ui": ("Poppins-SemiBold.ttf", "poppins/Poppins-SemiBold.ttf")}


def _font(kind, size):
    if kind == "big":
        p = font_path("Anton-Regular.ttf")
        return ImageFont.truetype(p, size) if p else ImageFont.load_default()
    name, rel = FONTS[kind]
    p = ROOT / "fonts" / name
    if not p.exists():
        try:
            r = requests.get(FONT_URL + rel, timeout=60)
            r.raise_for_status()
            if r.content[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                p.parent.mkdir(exist_ok=True)
                p.write_bytes(r.content)
        except Exception as e:
            log(f"font download {name}: {e}")
    if p.exists():
        return ImageFont.truetype(str(p), size)
    fb = font_path("x")                                       # DejaVu / Liberation fallback
    return ImageFont.truetype(fb, size) if fb else ImageFont.load_default()


# ------------------------------------------------------------------ writing
def _series_no(hist):
    return sum(1 for p in hist["posts"] if p.get("kind") == "post") + 1


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"[—–]", ", ", str(s))).strip().strip('"')


def _lines_ok(lines):
    if not (2 <= len(lines) <= 7) or not any(l["big"] for l in lines):
        return False
    return all(len(l["t"]) <= (16 if l["big"] else 46) for l in lines)


def _auto_lines(quote):
    """Fallback split if the AI's lines are unusable: short punchy chunks, alternating big/small."""
    words, lines, cur = quote.split(), [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) >= 11 or w[-1] in ".,?!:":
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return [{"t": t, "big": i % 2 == 0} for i, t in enumerate(lines)]


def write(cfg, hist):
    posts = [p for p in hist["posts"] if p.get("kind") == "post"]
    recent = [p.get("quote", "") for p in posts][-40:]
    used_styles = [p.get("format") for p in posts][-3:]
    style = random.choice([s for s in STYLES if s not in used_styles] or list(STYLES))
    theme = random.choice(cfg["themes"])
    prompt = f"""You write image posts for the Facebook page "{cfg['channel_name']}" (motivation for
English-speaking people 18-35 who feel stuck and want to change).
Theme: {theme}
Post type: {STYLES[style]}

The text is set like an editorial poster: some lines are BIG heavy capitals (the words that hit),
the rest are small elegant italic connecting words. Example of the shape (do NOT reuse it):
  [{{"t": "Comfort", "big": true}}, {{"t": "is a slow way", "big": false}},
   {{"t": "to lose", "big": false}}, {{"t": "everything.", "big": true}}]

Rules:
- 100% original wording. Never quote or name a real person. No cliches ("believe in yourself",
  "never give up", "hustle", "unleash", "journey", "embrace", "grind"). No emojis. No em/en dashes.
- 3 to 6 lines. BIG lines: 1-2 words, max 14 characters. Small lines: max 6 words.
- The lines read top to bottom as one natural sentence (or two).
- Clearly different from these recent posts:
{chr(10).join('  - ' + r for r in recent[-25:]) or '  - none'}

Return ONLY JSON:
{{"lines": [{{"t": "...", "big": true}}, ...],
  "key": "ONE word copied exactly from a BIG line, the most important word (it gets the gold frame)",
  "caption": "2-4 short lines for the post text: expand the idea with one concrete, everyday example, then end with a question that invites comments. Max 60 words. At most one emoji."}}"""
    for attempt in range(4):
        try:
            d = extract_json(ask(cfg, prompt, json_mode=True, temperature=1.0))
            lines = [{"t": _clean(l.get("t", "")), "big": bool(l.get("big"))}
                     for l in d.get("lines", []) if isinstance(l, dict) and _clean(l.get("t", ""))]
            quote = " ".join(l["t"] for l in lines)
            n = len(quote.split())
            if not 3 <= n <= 28:
                prompt += f"\n\nYour text had {n} words. Keep it between 5 and 24 words."
                continue
            if not _lines_ok(lines):
                log("post: line layout unusable, splitting automatically")
                lines = _auto_lines(quote)
            key = _clean(d.get("key", "")).strip(".,!?;:")
            bigwords = [w.strip(".,!?;:'\"").lower() for l in lines if l["big"] for w in l["t"].split()]
            if key.lower() not in bigwords:
                key = max((w for l in lines if l["big"] for w in l["t"].split()), key=len).strip(".,!?;:")
            no = _series_no(hist)
            out = {"lines": lines, "quote": quote, "key": key, "style": style, "theme": theme, "no": no,
                   "look": "paper" if no % 3 == 0 else "night", "photo": "",
                   "caption": _clean(d.get("caption") or quote)}
            log(f"post No.{no} | {style} | {out['look']} | {quote}")
            return out
        except Exception as e:
            log(f"post attempt {attempt + 1} failed: {str(e)[:200]}")
    raise RuntimeError("Could not write the post")


def find_photo(query, used):
    """The signature style is typographic: no stock photo (kept so main.py stays unchanged)."""
    return None


# ------------------------------------------------------------------ design
def _grain(img, amount):
    a = np.asarray(img).astype(np.int16)
    noise = np.random.default_rng().normal(0, amount, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8))


def _logo(look, height):
    p = ROOT / "assets" / "logo.png"
    if not p.exists():
        return None
    lg = Image.open(p).convert("RGBA")
    lg = lg.resize((int(lg.width * height / lg.height), height), Image.LANCZOS)
    if look == "paper":                       # white letters -> near-black, gold stays gold
        a = np.asarray(lg).astype(np.float32)
        rgb = a[..., :3]
        grey = (rgb.max(-1) - rgb.min(-1)) < 40
        rgb[grey] = (16, 16, 18)
        rgb[~grey] *= np.array([0.80, 0.74, 0.55])     # deeper gold so the HQ box reads on cream
        a[..., :3] = rgb
        lg = Image.fromarray(a.astype(np.uint8), "RGBA")
    return lg


def _spaced(draw, xy, text, font, fill, spacing, anchor_right=False):
    """Letter-spaced small caps text."""
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor_right:
        x -= total
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + spacing
    return total


def _layout(lines, key, max_w, max_h, scale):
    """Turn the lines into rows of words with fonts. Returns rows and total height."""
    big_size = int(196 * scale)
    small_size = int(70 * scale)
    fb, fs = _font("big", big_size), _font("serif", small_size)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    pad = int(big_size * 0.16)                       # room for the gold frame around the key word
    rows, framed = [], False
    for l in lines:
        f = fb if l["big"] else fs
        words = l["t"].upper().split() if l["big"] else l["t"].split()
        cur, cur_w = [], 0
        for w in words:
            is_key = not framed and l["big"] and w.strip(".,!?;:'\"").lower() == key.lower()
            framed = framed or is_key
            ww = probe.textlength(w, font=f) + (2 * pad if is_key else 0)
            sp = probe.textlength(" ", font=f)
            if cur and cur_w + sp + ww > max_w:
                rows.append({"big": l["big"], "font": f, "words": cur})
                cur, cur_w = [], 0
            cur.append((w, is_key, ww))
            cur_w += (sp if len(cur) > 1 else 0) + ww
        if cur:
            rows.append({"big": l["big"], "font": f, "words": cur})
    # row heights: caps sit tight, italic rows get air
    for r in rows:
        r["h"] = int(big_size * 0.96) if r["big"] else int(small_size * 1.28)
    total = sum(r["h"] for r in rows) + int(big_size * 0.10) * (len(rows) - 1)
    widest = max(sum(w[2] for w in r["words"]) + probe.textlength(" ", font=r["font"]) * (len(r["words"]) - 1)
                 for r in rows)
    return rows, total, widest, big_size, pad


def design(d, photo, out):
    t = THEMES[d.get("look", "night")]
    bg = Image.new("RGB", (W, H), t["bg"])
    if d.get("look", "night") == "night":                 # faint warm light from the top right
        yy, xx = np.mgrid[0:H, 0:W]
        glow = np.exp(-(((xx - W * 0.95) / 700) ** 2 + ((yy + 80) / 650) ** 2)) * 26
        a = np.asarray(bg).astype(np.float32) + glow[..., None] * np.array([1.0, 0.78, 0.25])
        bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    bg = _grain(bg, t["grain"]).convert("RGBA")
    dr = ImageDraw.Draw(bg)
    ui = _font("ui", 25)

    # --- header: logo left, series number right, thin rule
    lg = _logo(d.get("look"), 74)
    if lg:
        bg.alpha_composite(lg, (M, 78))
    _spaced(dr, (W - M, 98), f"NO. {d.get('no', 1):03d}", ui, t["rule"], 5, anchor_right=True)
    _spaced(dr, (W - M, 132), "DAILY DRIVE", _font("ui", 19), t["meta"], 6, anchor_right=True)

    # --- the quote block (left aligned, vertically centred between header and footer)
    top, bottom = 230, H - 200
    max_w, max_h = W - 2 * M, bottom - top
    scale = 1.3                                   # short quotes get bigger type
    while True:
        rows, total, widest, big_size, pad = _layout(d["lines"], d["key"], max_w, max_h, scale)
        if (total <= max_h and widest <= max_w) or scale < 0.45:
            break
        scale -= 0.05
    y = top + (max_h - total) // 2
    gap = int(big_size * 0.10)
    for r in rows:
        f = r["font"]
        x = M
        asc = -f.getbbox("H", anchor="ls")[1]            # cap height
        base = y + (r["h"] + asc) // 2 if r["big"] else y + int(r["h"] * 0.78)
        sp = dr.textlength(" ", font=f)
        for w, is_key, ww in r["words"]:
            if is_key:
                box = [x, base - asc - pad * 0.95, x + ww, base + pad * 0.95]
                dr.rounded_rectangle(box, radius=int(pad * 1.1), outline=t["rule"], width=max(5, int(big_size * 0.035)))
                dr.text((x + pad, base), w, font=f, fill=t["rule"], anchor="ls")
            else:
                dr.text((x, base), w, font=f, fill=t["big"] if r["big"] else t["small"], anchor="ls")
            x += ww + sp
        y += r["h"] + gap

    # --- footer: gold rules + handle
    fy = H - 112
    handle = "@THESTAYDRIVENHQ"
    hw = _spaced(dr, (0, -100), handle, ui, t["meta"], 7)      # measure only (drawn off-canvas)
    hx = (W - hw) / 2
    _spaced(dr, (hx, fy - 15), handle, ui, t["meta"], 7)
    dr.line([M, fy, hx - 30, fy], fill=t["rule"], width=2)
    dr.line([hx + hw + 30, fy, W - M, fy], fill=t["rule"], width=2)

    bg.convert("RGB").save(out, quality=94)
    log(f"post image saved ({Path(out).name})")
    return out


def caption_text(d, cfg):
    tags = " ".join(cfg.get("hashtags_meta", [])[:6])
    return f"{d['caption']}\n.\n.\n{tags}"
