import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def log(msg):
    print("SD | " + str(msg), flush=True)


def run(cmd, cwd=None, timeout=1800):
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:7]))} ...\n{p.stderr[-2000:]}")
    return p


def ffprobe_duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def font_path(name):
    p = ROOT / "fonts" / name
    if p.exists():
        return str(p)
    for alt in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if Path(alt).exists():
            return alt
    return None
