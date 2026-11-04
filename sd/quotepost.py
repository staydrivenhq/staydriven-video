"""Facebook motivational image posts (quote cards), between the videos.
Writes an original quote + caption, finds a matching dark cinematic photo on Pexels, designs a
1080x1350 card (Facebook's tallest feed size) with the logo, and posts it to the Page."""
import io
import os
import random
import re

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .footage import _blocked
from .llm import ask, extract_json, log
from .util import ROOT, font_path

W, H = 1080, 1350
GOLD = (255, 200, 53)

STYLES = {
    "quote": "One original, quotable line (8-22 words) that hits hard and is easy to screenshot and share.",
    "truth": "A hard truth in 2 short sentences (max 26 words): the first stings, the second lifts.",
    "reminder": "A daily reminder that starts with 'Reminder:' (max 22 words), calm but firm.",
    "question": "A sharp question to the reader (max 18 words) that makes them stop and think about their life.",
    "rule": "One life rule in the form 'Rule: ...' (max 18 words), concrete and actionable.",
}


def write(cfg, hist):
    recent = [p.get("quote", "") for p in hist["posts"] if p.get("kind") == "post"][-60:]
    used_styles = [p.get("format") for p in hist["posts"] if p.get("kind") == "post"][-3:]
    style = random.choice([s for s in STYLES if s not in used_styles] or list(STYLES))
    theme = random.choice(cfg["themes"])
    prompt = f"""You write Facebook posts for "{cfg['channel_name']}", a motivation page for English-speaking
people 18-35 who feel stuck and want to change.
Theme: {theme}
Post type: {STYLES[style]}

Rules:
- 100% original wording. Never quote or name a real person. No cliches like "believe in yourself",
  "never give up", "hustle", "unleash", "journey", "embrace". No emojis inside the quote.
- No em dashes or en dashes.
- Must be clearly different from these recent posts:
{chr(10).join('  - ' + r for r in recent[-25:]) or '  - none'}

Return ONLY JSON:
{{"quote": "the text on the image",
  "highlight": "ONE word copied exactly from the quote to show in gold",
  "caption": "2-4 short lines for the post text: expand the idea with one concrete example, then end with a question that invites comments. Max 60 words. At most one emoji.",
  "photo": "2-4 word search for a dark, cinematic, moody stock PHOTO that fits (a lone person, a road, mountains, storm, city at night, an athlete). No famous people, no text."}}"""
    for attempt in range(4):
        try:
            d = extract_json(ask(cfg, prompt, json_mode=True, temperature=1.0))
            q = re.sub(r"[—–]", ", ", str(d.get("quote", ""))).strip().strip('"')
            n = len(q.split())
            if 4 <= n <= 30:
                d["quote"] = q
                hl = str(d.get("highlight") or "").strip()
                d["highlight"] = hl if hl and hl.lower() in q.lower() else ""
                d["caption"] = re.sub(r"[—–]", ", ", str(d.get("caption") or q)).strip()
                d["photo"] = str(d.get("photo") or "dark mountain silhouette")
                d.update(style=style, theme=theme)
                log(f"post | {style} | {theme} | {q}")
                return d
            prompt += f"\n\nYour quote had {n} words. Keep it between 6 and 26 words."
        except Exception as e:
            log(f"post attempt {attempt + 1} failed: {str(e)[:200]}")
    raise RuntimeError("Could not write the post")


# ------------------------------------------------------------------ photo
FALLBACK_PHOTOS = ["man silhouette sunset", "mountain fog dark", "empty road night", "storm clouds dark",
                   "athlete training dark", "city night rain", "lonely man walking", "ocean waves dark"]


def find_photo(query, used):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    for q in [query, " ".join(query.split()[:2])] + random.sample(FALLBACK_PHOTOS, 3):
        try:
            r = requests.get("https://api.pexels.com/v1/search", timeout=30, headers={"Authorization": key},
                             params={"query": q, "orientation": "portrait", "per_page": 40, "size": "large"})
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"pexels photo '{q}': {e}")
            continue
        photos = [p for p in r.json().get("photos", [])
                  if f"pxp:{p['id']}" not in used and not _blocked(p.get("alt", "") + " " + p.get("url", ""))]
        random.shuffle(photos)
        for p in photos[:5]:
            try:
                img = requests.get(p["src"].get("large2x") or p["src"]["original"], timeout=60)
                img.raise_for_status()
                used.add(f"pxp:{p['id']}")
                return Image.open(io.BytesIO(img.content)).convert("RGB")
            except Exception as e:
                log(f"photo download failed: {e}")
    return None


def _cover(img):
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s + 0.5), int(img.height * s + 0.5)), Image.LANCZOS)
    l, t = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((l, t, l + W, t + H))


def _wrap(draw, words, font, max_w):
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and draw.textlength(test, font=font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def design(d, photo, out):
    if photo is None:
        bg = Image.new("RGB", (W, H), (14, 16, 22))
    else:
        bg = _cover(photo)
        bg = ImageEnhance.Color(bg).enhance(0.75)
        bg = ImageEnhance.Contrast(bg).enhance(1.08)
    # darken for text: overall + stronger in the middle band, vignette at the edges
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    bg = Image.blend(bg, dark, 0.42)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([0, int(H * 0.22), W, int(H * 0.78)], fill=120)
    mask = mask.filter(ImageFilter.GaussianBlur(140))
    bg = Image.composite(dark, bg, mask)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-220, -160, W + 220, H + 160], fill=255)
    bg = Image.composite(bg, dark, vig.filter(ImageFilter.GaussianBlur(160)))
    # light film grain so it doesn't look flat
    arr = np.asarray(bg).astype(np.int16)
    arr = np.clip(arr + np.random.default_rng().normal(0, 6, arr.shape[:2])[..., None], 0, 255).astype(np.uint8)
    bg = Image.fromarray(arr).convert("RGBA")

    words = d["quote"].upper().split()
    hl = d.get("highlight", "").upper().strip(".,!?;:")
    fp = font_path("Anton-Regular.ttf")
    size = 118
    while size > 58:
        f = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        probe = ImageDraw.Draw(bg)
        lines = _wrap(probe, words, f, W - 180)
        if len(lines) * size * 1.12 <= H * 0.52:
            break
        size -= 6
    lh = int(size * 1.12)
    y = (H - lh * len(lines)) // 2 - 20
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    td.rectangle([W // 2 - 50, y - 70, W // 2 + 50, y - 62], fill=GOLD)          # small gold bar above
    for line in lines:
        lw = td.textlength(" ".join(line), font=f)
        x = (W - lw) / 2
        for w in line:
            col = GOLD if hl and w.strip(".,!?;:") == hl else (255, 255, 255)
            td.text((x, y), w, font=f, fill=col)
            x += td.textlength(w + " ", font=f)
        y += lh
    shadow = txt.split()[3].filter(ImageFilter.GaussianBlur(10))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow.putalpha(shadow.point(lambda v: int(v * 0.9)))
    card = Image.alpha_composite(Image.alpha_composite(bg, glow), txt)

    logo_p = ROOT / "assets" / "logo.png"
    if logo_p.exists():
        logo = Image.open(logo_p).convert("RGBA")
        lw = 250
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        card.alpha_composite(logo, ((W - lw) // 2, H - logo.height - 70))
    card.convert("RGB").save(out, quality=93)
    log(f"post image saved ({out.name})")
    return out


def caption_text(d, cfg):
    tags = " ".join(cfg.get("hashtags_meta", [])[:6])
    return f"{d['caption']}\n.\n.\n{tags}"
