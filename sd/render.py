"""Cinematic render: shot plan (cut on words), color grade, slow camera drift, film grain,
letterbox, kinetic text, original score ducked under voice, SFX, loudness -14 LUFS (YouTube standard)."""
import math
import random
from pathlib import Path

from . import audio, captions
from .util import ROOT, ffprobe_duration, log, run

DIMS = {"long": (1920, 1080), "short": (1080, 1920)}
SHOT = {"long": (3.0, 5.2), "short": (1.5, 2.8)}
GRADE = ("colorbalance=rs=-0.035:bs=0.05:rm=0.0:bm=-0.01:rh=0.055:gh=0.01:bh=-0.06,"
         "eq=contrast=1.07:saturation=0.82:gamma=0.96")
# documentary: lifted blacks, warm muted film look (long videos)
DOC_GRADE = ("curves=master='0/0.045 0.25/0.22 0.75/0.76 1/0.96',"
             "colorbalance=rs=0.03:gs=0.01:bs=-0.035:rh=0.035:gh=0.01:bh=-0.045,"
             "eq=contrast=1.05:saturation=0.66")
LOGO = ROOT / "assets" / "logo.png"


def _look(kind, cfg):
    return "documentary" if kind == "long" and cfg.get("long_look", "documentary") == "documentary" else "cinematic"


# ------------------------------------------------------------ shot plan
def plan_shots(kind, segs, impacts, look="cinematic"):
    lo, hi = (3.8, 6.4) if look == "documentary" else SHOT[kind]
    shots = []
    impact_set = sorted(impacts)
    for s in segs:
        st, en = s["start"], s["start"] + s["dur"]
        if s.get("role") == "card":
            shots.append({"start": st, "dur": en - st, "query": s["visual"], "card": True})
            continue
        # candidate cut points = word starts (+ forced cuts on impact words)
        cuts = [st]
        word_starts = [w["start"] for w in s["words"][1:]]
        forced = [t for t in impact_set if st + 0.3 < t < en - 0.3]
        t = st
        while True:
            target = t + random.uniform(lo, hi)
            if target > en - lo * 0.6:
                break
            near = min(word_starts, key=lambda x: abs(x - target)) if word_starts else target
            if near - t < lo * 0.6 or abs(near - target) > 1.2:
                near = target
            cuts.append(near)
            t = near
        cuts = sorted(set([c for c in cuts if c - st > 0.4 or c == st] + forced))
        cuts.append(en)
        for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
            if b - a < 0.35:
                continue
            q = s["visual"] if k % 2 == 0 else s.get("visual2") or s["visual"]
            shots.append({"start": a, "dur": b - a, "query": q,
                          "impact": any(abs(a - x) < 0.05 for x in forced)})
    # merge tiny leftovers into the previous shot
    fixed = []
    for sh in shots:
        if fixed and sh["dur"] < 0.6 and not sh.get("card"):
            fixed[-1]["dur"] += sh["dur"]
        else:
            fixed.append(sh)
    # make shots perfectly contiguous
    for i in range(len(fixed) - 1):
        fixed[i]["dur"] = fixed[i + 1]["start"] - fixed[i]["start"]
    return fixed


# ------------------------------------------------------------ one shot
def _shot_filter(kind, sh, W, H, dur, look="cinematic"):
    zoom = 1.14 if sh.get("impact") else (1.07 if look == "documentary" else 1.10)
    sw, sh_ = int(W * zoom) // 2 * 2, int(H * zoom) // 2 * 2
    dx = random.choice([-1, 1])
    dy = random.choice([-1, 0, 1])
    amt = 0.42 if not sh.get("impact") else 0.9
    x = f"(in_w-out_w)*(0.5+{dx}*{amt}*(t/{dur:.3f}-0.5))"
    y = f"(in_h-out_h)*(0.5+{dy}*0.35*(t/{dur:.3f}-0.5))"
    vf = (f"scale={sw}:{sh_}:force_original_aspect_ratio=increase,crop={sw}:{sh_},"
          f"crop={W}:{H}:x='max(0,min(in_w-out_w,{x}))':y='max(0,min(in_h-out_h,{y}))',"
          f"fps=30,setsar=1,{DOC_GRADE if look == 'documentary' else GRADE}")
    if sh.get("card"):
        vf += ",gblur=sigma=22,eq=brightness=-0.12"
    return vf + ",format=yuv420p"


def render_shot(src, start, dur, kind, sh, out, look="cinematic"):
    W, H = DIMS[kind]
    net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4",
           "-rw_timeout", "30000000"] if str(src).startswith("http") else []
    run(["ffmpeg", "-y", "-loglevel", "error", *net, "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.3f}",
         "-vf", _shot_filter(kind, sh, W, H, dur, look), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "17", "-r", "30", out], timeout=400)


def build_footage(kind, shots, picker, work: Path, look="cinematic"):
    W, H = DIMS[kind]
    files = []
    for i, sh in enumerate(shots):
        out = work / f"shot_{i:04d}.mp4"
        for attempt in range(5):
            clip = picker(sh["query"], sh["dur"], W, H)
            room = max(0.0, min(clip["duration"] - sh["dur"] - 0.3, clip["duration"] * 0.55))
            try:
                render_shot(clip["url"], random.uniform(0, room), sh["dur"], kind, sh, out, look)
                break
            except Exception as e:
                log(f"shot {i} clip failed ({clip.get('id')}): {str(e)[-160:]}")
        else:
            raise RuntimeError("too many footage failures")
        files.append(out)
        if i % 20 == 0:
            log(f"{kind}: shot {i + 1}/{len(shots)}")
    (work / "shots.txt").write_text("".join(f"file '{f.name}'\n" for f in files))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "shots.txt",
         "-c", "copy", "footage.mp4"], cwd=work)
    return work / "footage.mp4"


# ------------------------------------------------------------ sound
def intensity_fn(kind, segs, total):
    if kind == "short":
        return lambda t: 1 if t < total * 0.35 else (2 if t < total * 0.75 else 3)
    marks = []
    for s in segs:
        if s.get("role") == "card":
            marks.append(s["start"])
    close = next((s["start"] for s in segs if s.get("role") == "close"), total * 0.85)

    def f(t):
        if t < (marks[0] if marks else 25):
            return 0
        if t >= close:
            return 3
        done = sum(1 for m in marks if t >= m)
        return 1 if done <= max(1, len(marks) // 2) else 2
    return f


def make_audio(kind, segs, total, sfx_events, cfg, work, seed):
    tracks = audio.user_tracks()
    if tracks:
        music = random.choice(tracks)
        log(f"music: {music.name}")
        mus_args = ["-stream_loop", "-1", "-i", str(music)]
    else:
        music = audio.make_score(total + 1, intensity_fn(kind, segs, total), work / "score.wav", seed,
                                 bpm=random.choice([68, 72, 76]))
        mus_args = ["-i", str(music)]
    sfx_path = None
    if cfg.get("sfx", True) and sfx_events:
        sfx_path = audio.make_sfx(total + 1, sfx_events, work / "sfx.wav")
    return mus_args, sfx_path


# ------------------------------------------------------------ final
def _count_inputs(args):
    return sum(1 for a in args if a == "-i")


def finish(kind, footage, voice, ass, mus_args, sfx_path, cfg, total, out, look="cinematic"):
    W, H = DIMS[kind]
    end = total + (1.0 if kind == "short" else 1.6)
    grain = int(cfg.get("film_grain", 7)) + (4 if look == "documentary" else 0)
    v = "[0:v]tpad=stop_mode=clone:stop_duration=5"
    v += ",vignette=angle=PI/4.6"
    if grain:
        v += f",noise=alls={grain}:allf=t"
    if kind == "long" and cfg.get("letterbox_long", True):
        bar = 96
        v += f",drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill"
    v += f",ass={ass.name}:fontsdir={ROOT / 'fonts'}"
    inputs = ["-i", footage.name, "-i", voice.name] + mus_args
    logo = LOGO.exists() and cfg.get("brand_watermark", True)
    v += "[base]"
    chain = v
    extra = []
    if logo:
        # small watermark: inside the top cinema bar (long) / top-right (short)
        wm_w = 210 if kind == "long" else 230
        wm_x, wm_y = (W - wm_w - 40, 14) if kind == "long" else (W - wm_w - 44, 120)
        extra = ["-loop", "1", "-framerate", "30", "-t", f"{end:.2f}", "-i", str(LOGO)]
        chain += (f";[LOGO]format=rgba,split=2[lg1][lg2];"
                  f"[lg1]scale={wm_w}:-1,colorchannelmixer=aa=0.82[wm];"
                  f"[base][wm]overlay={wm_x}:{wm_y}:format=auto[b2]")
        if kind == "long":
            st = max(0.0, total - 4.0)
            chain += (f";[lg2]scale=760:-1,fade=t=in:st={st:.2f}:d=0.6:alpha=1[big];"
                      f"[b2][big]overlay=(W-w)/2:(H-h)/2-40:format=auto:enable='gte(t,{st:.2f})'[b3]")
            last = "[b3]"
        else:
            chain += ";[lg2]nullsink"
            last = "[b2]"
    else:
        last = "[base]"
    chain += f";{last}fade=t=in:st=0:d=0.35,fade=t=out:st={end - 0.7:.2f}:d=0.7,format=yuv420p[v]"
    v = chain
    a = (f"[1:a]aformat=channel_layouts=stereo,apad[vo];[vo]asplit=2[vo1][vo2];"
         f"[2:a]aformat=channel_layouts=stereo,volume={cfg.get('music_volume', 0.16) * 2.2:.3f},"
         f"afade=t=out:st={end - 2.5:.2f}:d=2.5[mu];"
         f"[mu][vo2]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=450[duck];")
    mix_in = "[vo1][duck]"
    n = 2
    if sfx_path:
        inputs += ["-i", str(sfx_path)]
        a += "[3:a]aformat=channel_layouts=stereo,volume=0.9[fx];"
        mix_in += "[fx]"
        n = 3
    if logo:
        v = v.replace("[LOGO]", f"[{_count_inputs(inputs)}:v]")
        inputs += extra
    a += (f"{mix_in}amix=inputs={n}:duration=first:normalize=0,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    rate = ["-crf", "21", "-maxrate", "8M", "-bufsize", "16M"] if kind == "long" else \
        ["-crf", "19", "-maxrate", "14M", "-bufsize", "28M"]
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", f"{v};{a}",
         "-map", "[v]", "-map", "[a]", "-t", f"{end:.2f}", "-c:v", "libx264", "-preset", "fast" if kind == "long" else "medium",
         "-profile:v", "high", "-pix_fmt", "yuv420p", *rate, "-g", "60", "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart", out.name], cwd=out.parent, timeout=5400)
    log(f"{kind} final: {out.name} {ffprobe_duration(out):.1f}s {out.stat().st_size / 1e6:.0f} MB")


def make_video(kind, segs, voice, total, cfg, picker, work: Path, hook_text=None, seed=1):
    ass = work / "subs.ass"
    letterbox = kind == "long" and cfg.get("letterbox_long", True)
    look = _look(kind, cfg)
    sfx_events, impacts = captions.build(kind, segs, total, cfg, ass, hook_text=hook_text, letterbox=letterbox)
    shots = plan_shots(kind, segs, impacts, look)
    log(f"{kind}: {len(shots)} shots for {total:.0f}s ({look} look)")
    footage = build_footage(kind, shots, picker, work, look)
    mus_args, sfx_path = make_audio(kind, segs, total, sfx_events, cfg, work, seed)
    out = work / f"{kind}.mp4"
    finish(kind, footage, voice, ass, mus_args, sfx_path, cfg, total, out, look)
    captions.srt(segs, work / "captions.srt")
    return out, footage, shots
