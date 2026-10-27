"""Click-worthy (kintu content-er sathe mil) thumbnail: cinematic background + 2-4 boro shobdo."""
import base64
import io
import os
import random
import re
import subprocess

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .util import font_path, log

TW, TH = 1280, 720
GOLD = (255, 200, 53)
RED = (232, 48, 48)


def cloudflare_bg(scene):
    acc, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not (acc and tok):
        return None
    prompt = (f"{scene}. Cinematic film still, dramatic rim lighting, high contrast, moody teal and orange "
              "color grade, shallow depth of field, photorealistic, lots of dark empty space on the left side, "
              "no text, no logo, no watermark")
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                          headers={"Authorization": f"Bearer {tok}"}, json={"prompt": prompt, "steps": 8},
                          timeout=120)
        r.raise_for_status()
        img = Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"]))).convert("RGB")
        log("thumbnail: AI background (Cloudflare)")
        return img
    except Exception as e:
        log(f"thumbnail: Cloudflare failed ({str(e)[:150]}), using a video frame")
        return None


def _frame(video, t):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB") if p.stdout else None


def best_frame(footage, shots):
    cands = [s for s in shots if not s.get("card") and s["dur"] > 1.2]
    random.shuffle(cands)
    best, best_score = None, -1
    for s in cands[:16]:
        img = _frame(footage, s["start"] + s["dur"] * 0.5)
        if img is None:
            continue
        g = np.asarray(img.convert("L").resize((320, 180)), dtype=np.float32)
        lap = np.abs(np.diff(g, 2, axis=0)).mean() + np.abs(np.diff(g, 2, axis=1)).mean()
        bright = g.mean()
        score = lap * 2 + g.std() * 0.6 - abs(bright - 95) * 0.25
        if score > best_score:
            best, best_score = img, score
    return best


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s + 0.5), int(img.height * s + 0.5)), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def make(title_words, scene, footage, shots, out, mode="auto"):
    bg = cloudflare_bg(scene) if mode in ("auto", "ai") else None
    if bg is None:
        bg = best_frame(footage, shots) or Image.new("RGB", (TW, TH), (12, 14, 20))
    bg = cover(bg, TW, TH)
    bg = ImageEnhance.Contrast(bg).enhance(1.18)
    bg = ImageEnhance.Color(bg).enhance(1.08)
    bg = ImageEnhance.Sharpness(bg).enhance(1.3)

    # left dark gradient + vignette for text
    grad = Image.new("L", (TW, TH))
    gp = grad.load()
    for x in range(TW):
        a = int(max(0, 215 - x * 0.33))
        for y in range(0, TH, 1):
            gp[x, y] = a
    black = Image.new("RGB", (TW, TH), (0, 0, 0))
    bg = Image.composite(black, bg, grad)
    vig = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(vig).ellipse([-260, -200, TW + 260, TH + 200], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    bg = Image.composite(bg, black, vig)

    # words: *gold* word
    raw = title_words.strip().upper()
    tokens = raw.replace("*", " * ").split()
    words, hl, on = [], set(), False
    for t in tokens:
        if t == "*":
            on = not on
            continue
        if on:
            hl.add(len(words))
        words.append(t)
    if not hl and words:
        hl.add(max(range(len(words)), key=lambda i: len(words[i])))
    lines = [words] if len(words) <= 2 else [words[:len(words) // 2], words[len(words) // 2:]]

    fp = font_path("Anton-Regular.ttf")
    max_w = int(TW * 0.58)
    size = 210
    while size > 90:
        f = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        dd = ImageDraw.Draw(bg)
        widths = [dd.textlength(" ".join(l), font=f) for l in lines]
        if max(widths) <= max_w and size * 1.05 * len(lines) < TH * 0.72:
            break
        size -= 8
    lh = int(size * 1.04)
    y0 = (TH - lh * len(lines)) // 2 - 10

    txt = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    idx = 0
    y = y0
    for line in lines:
        x = 70
        for w in line:
            col = GOLD if idx in hl else (255, 255, 255)
            d.text((x, y), w, font=f, fill=col, stroke_width=max(6, size // 18), stroke_fill=(0, 0, 0))
            x += d.textlength(w + " ", font=f)
            idx += 1
        y += lh
    bottom = d.textbbox((70, y - lh), " ".join(lines[-1]), font=f)[3]
    d.rectangle([74, bottom + 22, 74 + int(max_w * 0.38), bottom + 36], fill=RED)
    shadow = txt.split()[3].filter(ImageFilter.GaussianBlur(14))
    glow = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    glow.putalpha(shadow.point(lambda v: int(v * 0.85)))
    base = bg.convert("RGBA")
    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, txt)
    base.convert("RGB").save(out, quality=92)
    log(f"thumbnail saved ({out.name})")
    return out
