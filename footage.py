"""Free stock footage: Pexels + Pixabay (dui jaygay khoje, beshi variety)."""
import os
import random
import time

import re

import requests

from .util import log

FALLBACK = ["silhouette man sunrise", "athlete training slow motion", "boxer training dark gym",
            "storm clouds timelapse", "ocean waves crashing slow motion", "man walking alone road",
            "city lights night aerial", "mountain summit hiker", "rain on window night",
            "runner stairs sunrise", "fire burning slow motion", "lone tree field fog"]


# off-brand or fake-looking (CGI / religion / fantasy / horror) footage is skipped
BLOCK = re.compile(r"\b(cross|crucifix|church|jesus|christ|god|bible|pray|prayer|religio\w*|islam|mosque|temple|"
                   r"buddha|demon|devil|satan|monster|skull|zombie|halloween|horror|ghost|dragon|fantasy|"
                   r"magic|alien|3d|cgi|render\w*|animation|animated|cartoon|ai|generated|abstract|"
                   r"loop|motion graphics?|background|particles?|hologram|neon sign|text|logo|flag)\b", re.I)


def _blocked(text):
    return bool(BLOCK.search(str(text or "").replace("-", " ")))


class Footage:
    def __init__(self, orientation, used: set):
        self.orientation = orientation          # landscape | portrait
        self.used = used
        self.cache = {}
        self.pexels = os.environ.get("PEXELS_API_KEY")
        self.pixabay = os.environ.get("PIXABAY_API_KEY")
        self.recent_creators = []        # same photographer = same location; avoid back-to-back

    # ---- search ----
    def _pexels(self, q):
        if not self.pexels:
            return []
        try:
            r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                             headers={"Authorization": self.pexels},
                             params={"query": q, "orientation": self.orientation, "per_page": 40, "size": "medium"})
            if r.status_code == 429:
                time.sleep(15)
                return []
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"pexels '{q}': {e}")
            return []
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
            if _blocked(v.get("url", "")):
                continue
            out.append({"id": f"px:{v['id']}", "duration": v.get("duration", 0),
                        "creator": f"px:{(v.get('user') or {}).get('id')}",
                        "files": [{"url": f["link"], "w": f["width"], "h": f["height"]} for f in files]})
        return out

    def _pixabay(self, q):
        if not self.pixabay:
            return []
        try:
            r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                             params={"key": self.pixabay, "q": q[:100], "per_page": 50, "safesearch": "true",
                                     "video_type": "film"})
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"pixabay '{q}': {e}")
            return []
        out = []
        for h in r.json().get("hits", []):
            if _blocked(h.get("tags", "")):
                continue
            files = [{"url": f["url"], "w": f["width"], "h": f["height"]}
                     for f in h.get("videos", {}).values() if f.get("url") and f.get("width")]
            out.append({"id": f"pb:{h['id']}", "duration": h.get("duration", 0), "files": files,
                        "creator": f"pb:{h.get('user_id')}"})
        return out

    def _search(self, q):
        if q not in self.cache:
            vids = self._pexels(q) + self._pixabay(q)
            random.shuffle(vids)
            self.cache[q] = vids
        return self.cache[q]

    def _file(self, v, W, H):
        want_portrait = self.orientation == "portrait"
        fs = [f for f in v["files"] if (f["h"] > f["w"]) == want_portrait]
        if not fs:
            return None
        good = [f for f in fs if f["w"] >= W * 0.95 and f["h"] >= H * 0.95]
        if good:
            return min(good, key=lambda f: f["w"] * f["h"])
        best = max(fs, key=lambda f: f["w"] * f["h"])
        # chhoto file (blurry) bad
        return best if best["h"] >= H * 0.6 else None

    def pick(self, query, need, W, H):
        queries = [query, query + " cinematic", " ".join(query.split()[:2])] + random.sample(FALLBACK, 4)
        for reuse in (False, True):
            for strict in (True, False):
                for q in queries:
                    for v in self._search(q):
                        if v["duration"] < need + 0.4 or (v["id"] in self.used and not reuse):
                            continue
                        if strict and v.get("creator") in self.recent_creators:
                            continue
                        f = self._file(v, W, H)
                        if not f:
                            continue
                        self.used.add(v["id"])
                        self.recent_creators = (self.recent_creators + [v.get("creator")])[-3:]
                        return {"id": v["id"], "url": f["url"], "duration": v["duration"], "query": q}
        raise RuntimeError("no footage for " + query)
