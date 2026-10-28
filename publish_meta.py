"""Facebook Page (video + Reel) ar Instagram Reel."""
import os
import time

import requests

from .util import log

V = os.environ.get("FB_GRAPH_VERSION", "v23.0")
G = f"https://graph.facebook.com/{V}"


def _tok():
    return os.environ["FB_PAGE_TOKEN"]


# ---------------- Facebook ----------------
def fb_video(path, title, description):
    page = os.environ["FB_PAGE_ID"]
    for attempt in range(3):
        with open(path, "rb") as fh:
            r = requests.post(f"https://graph-video.facebook.com/{V}/{page}/videos", timeout=3600,
                              data={"access_token": _tok(), "title": title[:250], "description": description},
                              files={"source": (os.path.basename(path), fh, "video/mp4")})
        if r.ok:
            log(f"facebook: video posted {r.json().get('id')}")
            return r.json().get("id")
        log(f"facebook video attempt {attempt + 1}: {r.text[:300]}")
        time.sleep(20)
    raise RuntimeError("Facebook video failed: " + r.text[:300])


def fb_reel(path, description):
    page = os.environ["FB_PAGE_ID"]
    r = requests.post(f"{G}/{page}/video_reels", data={"upload_phase": "start", "access_token": _tok()}, timeout=60)
    r.raise_for_status()
    vid, url = r.json()["video_id"], r.json()["upload_url"]
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        u = requests.post(url, data=fh, timeout=1200, headers={
            "Authorization": f"OAuth {_tok()}", "offset": "0", "file_size": str(size)})
    u.raise_for_status()
    f = requests.post(f"{G}/{page}/video_reels", timeout=120, data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": description, "access_token": _tok()})
    if not f.ok:
        raise RuntimeError("Facebook reel failed: " + f.text[:300])
    log(f"facebook: reel published {vid}")
    return vid


# ---------------- Instagram ----------------
def _ig_wait_and_publish(ig, cid):
    for _ in range(60):
        s = requests.get(f"{G}/{cid}", params={"fields": "status_code,status", "access_token": _tok()}, timeout=30)
        code = s.json().get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("Instagram processing error: " + str(s.json())[:300])
        time.sleep(10)
    p = requests.post(f"{G}/{ig}/media_publish", data={"creation_id": cid, "access_token": _tok()}, timeout=60)
    if not p.ok:
        raise RuntimeError("Instagram publish failed: " + p.text[:300])
    log(f"instagram: reel published {p.json().get('id')}")
    return p.json().get("id")


def _ig_container(ig, caption, ai_label, extra):
    data = {"media_type": "REELS", "caption": caption, "share_to_feed": "true", "access_token": _tok(), **extra}
    if ai_label:
        data["is_ai_generated"] = "true"
    r = requests.post(f"{G}/{ig}/media", data=data, timeout=120)
    if not r.ok and ai_label and "is_ai_generated" in r.text:
        data.pop("is_ai_generated")
        log("instagram: AI-label field not accepted by this API version, posting without it")
        r = requests.post(f"{G}/{ig}/media", data=data, timeout=120)
    return r


def ig_reel(path, caption, ai_label=True):
    ig = os.environ["IG_USER_ID"]
    # 1) resumable upload straight from this computer
    try:
        r = _ig_container(ig, caption, ai_label, {"upload_type": "resumable"})
        r.raise_for_status()
        cid = r.json()["id"]
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            u = requests.post(f"https://rupload.facebook.com/ig-api-upload/{V}/{cid}", data=fh, timeout=1200,
                              headers={"Authorization": f"OAuth {_tok()}", "offset": "0", "file_size": str(size)})
        u.raise_for_status()
        return _ig_wait_and_publish(ig, cid)
    except Exception as e:
        log(f"instagram: direct upload not possible ({str(e)[:200]}), trying public link")
    # 2) public link via a temporary GitHub release (repo must be public)
    url, cleanup = _temp_public_url(path)
    try:
        r = _ig_container(ig, caption, ai_label, {"video_url": url})
        if not r.ok:
            raise RuntimeError("Instagram container failed: " + r.text[:300])
        return _ig_wait_and_publish(ig, r.json()["id"])
    finally:
        cleanup()


def _temp_public_url(path):
    repo, tok = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and tok):
        raise RuntimeError("no public link possible (GITHUB_TOKEN missing)")
    H = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    tag = f"ig-temp-{int(time.time())}"
    rel = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=H, timeout=60,
                        json={"tag_name": tag, "name": tag, "prerelease": True,
                              "body": "Temporary file for Instagram. Deleted automatically."})
    rel.raise_for_status()
    rid = rel.json()["id"]
    up = rel.json()["upload_url"].split("{")[0]
    with open(path, "rb") as fh:
        a = requests.post(f"{up}?name=reel.mp4", headers={**H, "Content-Type": "video/mp4"}, data=fh, timeout=900)
    a.raise_for_status()
    url = a.json()["browser_download_url"]

    def cleanup():
        requests.delete(f"https://api.github.com/repos/{repo}/releases/{rid}", headers=H, timeout=60)
        requests.delete(f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}", headers=H, timeout=60)
    return url, cleanup
