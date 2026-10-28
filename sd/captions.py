"""Kinetic typography (ASS/libass): word-pop caption, impact slam + shake + flash, point card,
hook title, progress bar, brand bug. Sob motion libass e hoy, tai render fast."""
import re

LONG = dict(W=1920, H=1080, cap_size=84, cap_y=1080 - 160, group=4, max_chars=30,
            impact_size=270, card_size=150)
SHORT = dict(W=1080, H=1920, cap_size=110, cap_y=1150, group=3, max_chars=16,
             impact_size=270, card_size=120)


def ts(t):
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def esc(t):
    return re.sub(r"[{}\\]", "", str(t)).replace("\n", " ").strip()


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def header(P, cfg):
    gold = cfg.get("caption_gold", "&H0035C8FF")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {P['W']}
PlayResY: {P['H']}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Anton,{P['cap_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,1.5,0,1,{5 if P['W'] < P['H'] else 4},3,5,60,60,0,1
Style: Impact,Anton,{P['impact_size']},{gold},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,7,5,5,40,40,0,1
Style: Label,Bebas Neue,{76 if P['W'] > P['H'] else 70},{gold},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,10,0,1,2,2,5,40,40,0,1
Style: Head,Anton,{P['card_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,2,0,1,5,4,5,140,140,0,1
Style: Hook,Anton,{int(P['cap_size'] * 1.35)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,1.5,0,1,6,4,5,70,70,0,1
Style: Brand,Bebas Neue,{34 if P['W'] > P['H'] else 40},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,8,0,1,0,0,9,40,40,0,1
Style: Box,Anton,10,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ev(layer, st, en, style, text):
    if en - st < 0.02:
        return None
    return f"Dialogue: {layer},{ts(st)},{ts(en)},{style},,0,0,0,,{text}"


def _rect(P, color, alpha):
    W, H = P["W"], P["H"]
    return f"{{\\an7\\pos(0,0)\\bord0\\shad0\\p1\\1c{color}\\alpha{alpha}}}m 0 0 l {W} 0 {W} {H} 0 {H}{{\\p0}}"


def _groups(words, P, impact_norm):
    groups, cur = [], []
    for w in words:
        if _norm(w["word"]) == impact_norm and impact_norm:
            if cur:
                groups.append(cur)
            groups.append([dict(w, impact=True)])
            cur = []
            continue
        cur.append(w)
        chars = sum(len(x["word"]) + 1 for x in cur)
        if len(cur) >= P["group"] or chars >= P["max_chars"] or re.search(r"[.!?,;:]$", w["word"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build(kind, segs, total, cfg, out_path, hook_text=None, letterbox=False):
    P = LONG if kind == "long" else SHORT
    gold = cfg.get("caption_gold", "&H0035C8FF")
    red = cfg.get("caption_red", "&H003030E8")
    W, H = P["W"], P["H"]
    cx = W // 2
    upper = kind == "short"
    ev = []
    sfx = []          # (kind, time) for the sound designer
    impacts = []      # times (for footage cuts)

    # ---------- brand bug ----------
    from .util import ROOT
    has_logo = (ROOT / "assets" / "logo.png").exists()
    if cfg.get("brand_watermark", True) and not has_logo:
        y = 34 if (kind == "long" and letterbox) else (60 if kind == "long" else 150)
        x = W - 48 if kind == "long" else W - 56
        ev.append(_ev(9, 0, total + 1, "Brand",
                      f"{{\\an9\\pos({x},{y})\\alpha&H70&}}STAY {{\\c{gold}}}DRIVEN"))

    # ---------- short: hook title at second 0 + progress bar ----------
    if kind == "short":
        hook = esc(hook_text or segs[0]["text"]).upper()
        words = hook.split()
        per = 2 if len(words) <= 4 else 3
        # gold on the most emotional (longest) word
        if words:
            k = max(range(len(words)), key=lambda i: len(re.sub(r"\W", "", words[i])))
            words[k] = f"{{\\c{gold}}}{words[k]}{{\\c&HFFFFFF&}}"
        hook_end = segs[0]["start"] + segs[0]["dur"]
        ev.append(_ev(6, 0, hook_end, "Hook",
                      f"{{\\an5\\pos({cx},560)\\q0\\fscx100\\fscy100\\t(0,{int(hook_end * 1000)},\\fscx107\\fscy107)"
                      f"\\fad(0,180)}}" + "\\N".join(" ".join(words[i:i + per]) for i in range(0, len(words), per))))
        ev.append(_ev(8, 0, total + 1, "Box",
                      f"{{\\an7\\pos(0,{H - 10})\\bord0\\shad0\\p1\\1c{gold}\\alpha&H20&\\fscx0"
                      f"\\t(0,{int(total * 1000)},\\fscx100)}}m 0 0 l {W} 0 {W} 10 0 10{{\\p0}}"))

    for si, s in enumerate(segs):
        st, en = s["start"], s["start"] + s["dur"]
        role = s.get("role")

        # ---------- point card ----------
        if role == "card":
            d_ms = int((en - st) * 1000)
            ev.append(_ev(1, st, en, "Box", _rect(P, "&H000000&", "&H60&")))
            ly = H // 2 - (150 if kind == "long" else 230)
            ev.append(_ev(5, st, en, "Label",
                          f"{{\\an5\\pos({cx},{ly})\\fsp24\\alpha&HFF&\\t(0,350,\\alpha&H00&\\fsp10)\\fad(0,250)}}"
                          f"{esc(s.get('label', ''))}"))
            line_w = 260
            ev.append(_ev(5, st, en, "Box",
                          f"{{\\an5\\pos({cx},{ly + 52})\\bord0\\shad0\\p1\\1c{gold}\\fscx0"
                          f"\\t(120,520,\\fscx100)\\fad(0,250)}}m 0 0 l {line_w} 0 {line_w} 6 0 6{{\\p0}}"))
            head = esc(s.get("heading", "")).upper()
            ev.append(_ev(6, st + 0.12, en, "Head",
                          f"{{\\an5\\pos({cx},{H // 2 + (40 if kind == 'long' else 60)})\\q0\\blur14\\alpha&HFF&"
                          f"\\fscx114\\fscy114\\t(0,520,\\blur0\\alpha&H00&\\fscx100\\fscy100)"
                          f"\\t(520,{max(600, d_ms)},\\fscx104\\fscy104)\\fad(0,260)}}{head}"))
            sfx.append(("riser", st))
            sfx.append(("boom", st + 0.12))
            continue

        # ---------- documentary lower third (place / year / source from research) ----------
        lt = esc(s.get("lower_third") or "").upper()
        if lt:
            lt_en = min(en, st + 3.6)
            x0 = 120 if kind == "long" else 70
            y0 = (H - 300) if kind == "long" else 330
            ev.append(_ev(5, st + 0.2, lt_en, "Box",
                          f"{{\\an7\\pos({x0},{y0})\\bord0\\shad0\\p1\\1c{gold}\\fscy0\\t(0,200,\\fscy100)"
                          f"\\fad(0,250)}}m 0 0 l 8 0 8 64 0 64{{\\p0}}"))
            ev.append(_ev(5, st + 0.35, lt_en, "Label",
                          f"{{\\an4\\pos({x0 + 28},{y0 + 32})\\fsp14\\c&HFFFFFF&\\alpha&HFF&"
                          f"\\t(0,350,\\alpha&H00&\\fsp6)\\fad(0,250)}}{lt}"))

        # ---------- spoken captions ----------
        imp = _norm(s.get("impact") or "")
        groups = _groups(s["words"], P, imp)
        for gi, g in enumerate(groups):
            g_st = g[0]["start"]
            g_en = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else min(g[-1]["end"] + 0.35, en)
            if g_en <= g_st:
                continue
            if kind == "short" and si == 0:
                continue                                  # hook title already on screen

            # impact slam
            if g[0].get("impact"):
                word = esc(g[0]["word"]).upper().strip(".,!?;:")
                hold_en = min(max(g_en, g_st + 0.75), g_st + 1.3)
                y = H // 2 - (20 if kind == "long" else 40)
                shakes = [(0.00, 14, -10, 150), (0.04, -12, 8, 128), (0.08, 7, -4, 112), (0.12, -3, 2, 104)]
                for k, (off, dx, dy, sc) in enumerate(shakes):
                    a = g_st + off
                    b = g_st + (shakes[k + 1][0] if k + 1 < len(shakes) else 0.16)
                    ev.append(_ev(7, a, b, "Impact",
                                  f"{{\\an5\\pos({cx + dx},{y + dy})\\fscx{sc}\\fscy{sc}\\blur{2 if k < 2 else 0}}}{word}"))
                ev.append(_ev(7, g_st + 0.16, hold_en, "Impact",
                              f"{{\\an5\\pos({cx},{y})\\fscx100\\fscy100"
                              f"\\t(0,{int((hold_en - g_st) * 1000)},\\fscx106\\fscy106)\\fad(0,160)}}{word}"))
                bar = 420 if kind == "long" else 360
                ev.append(_ev(6, g_st + 0.08, hold_en, "Box",
                              f"{{\\an5\\pos({cx},{y + P['impact_size'] // 2 + 26})\\bord0\\shad0\\p1\\1c{red}"
                              f"\\fscx0\\t(0,180,\\fscx100)\\fad(0,160)}}m 0 0 l {bar} 0 {bar} 10 0 10{{\\p0}}"))
                ev.append(_ev(2, g_st, g_st + 0.2, "Box",
                              _rect(P, "&HFFFFFF&", "&H90&").replace("\\alpha&H90&", "\\alpha&H90&\\t(0,200,\\alpha&HFF&)")))
                ev.append(_ev(1, g_st, hold_en, "Box", _rect(P, "&H000000&", "&HA0&")))
                sfx.append(("boom", g_st))
                impacts.append(g_st)
                continue

            words = [esc(w["word"]) for w in g]
            if upper:
                words = [w.upper() for w in words]
            y = P["cap_y"]
            for wi, w in enumerate(g):
                a = w["start"]
                b = g[wi + 1]["start"] if wi + 1 < len(g) else g_en
                if b - a < 0.02:
                    continue
                if kind == "short":
                    # whole phrase on screen, the spoken word pops in gold
                    shown = []
                    for k in range(len(words)):
                        if k == wi:
                            shown.append(f"{{\\c{gold}\\fscx118\\fscy118\\t(0,120,\\fscx106\\fscy106)}}"
                                         f"{words[k]}{{\\c&HFFFFFF&\\fscx100\\fscy100}}")
                        else:
                            shown.append(words[k])
                    pop = "\\fscx90\\fscy90\\t(0,110,\\fscx100\\fscy100)" if wi == 0 else ""
                    text = f"{{\\an5\\pos({cx},{y}){pop}}}" + " ".join(shown)
                else:
                    shown = [(f"{{\\c{gold}}}{t}{{\\c&HFFFFFF&}}" if k == wi else t) for k, t in enumerate(words)]
                    pop = "\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)\\fad(70,0)" if wi == 0 else ""
                    text = f"{{\\an5\\pos({cx},{y}){pop}}}" + " ".join(shown)
                ev.append(_ev(4, a, b, "Cap", text))

        if role == "hook" and si == 0 and kind == "long":
            sfx.append(("boom", 0.05))

    # ---------- long: end card ----------
    if kind == "long":
        st = max(0, total - 4.2)
        ev.append(_ev(1, st, total + 1, "Box", _rect(P, "&H000000&", "&H50&").replace(
            "\\alpha&H50&", "\\alpha&HFF&\\t(0,600,\\alpha&H50&)")))
        if not has_logo:
            ev.append(_ev(6, st + 0.3, total + 1, "Head",
                          f"{{\\an5\\pos({cx},{H // 2 - 30})\\alpha&HFF&\\t(0,500,\\alpha&H00&)}}STAY {{\\c{gold}}}DRIVEN"))
        ev.append(_ev(6, st + 0.8, total + 1, "Label",
                      f"{{\\an5\\pos({cx},{H // 2 + 150})\\alpha&HFF&\\t(0,400,\\alpha&H00&)}}NEW VIDEO EVERY DAY"))

    out_path.write_text(header(P, cfg) + "\n".join(e for e in ev if e) + "\n", encoding="utf-8")
    return sfx, impacts


def srt(segs, path):
    """YouTube er jonno nikhut subtitle file."""
    lines, n = [], 1

    def f(t):
        h, r = divmod(max(0, t), 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    for s in segs:
        ws = s["words"]
        chunk = []
        for i, w in enumerate(ws):
            chunk.append(w)
            if len(chunk) >= 8 or i == len(ws) - 1 or re.search(r"[.!?]$", w["word"]):
                lines.append(f"{n}\n{f(chunk[0]['start'])} --> {f(chunk[-1]['end'] + 0.15)}\n"
                             + " ".join(x["word"] for x in chunk) + "\n")
                n += 1
                chunk = []
    path.write_text("\n".join(lines), encoding="utf-8")
