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
def _fb_post(url, data, files=None, timeout=600, tries=5):
    """POST with retries on network errors / 5xx. Returns the JSON or raises with Meta's message."""
    last = ""
    for attempt in range(tries):
        try:
            r = requests.post(url, data=data, files=files, timeout=timeout)
            if r.ok:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:400]}"
            if r.status_code < 500 and '"is_transient":true' not in r.text:
                break                                   # permission / bad request: retry won't help
        except requests.RequestException as e:
            last = str(e)[:300]
        log(f"facebook retry {attempt + 1}: {last[:200]}")
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(last)


def fb_video(path, title, description):
    """Long video -> Page video, uploaded in chunks (Meta's way for big files)."""
    page = os.environ["FB_PAGE_ID"]
    url = f"https://graph-video.facebook.com/{V}/{page}/videos"
    size = os.path.getsize(path)
    log(f"facebook: uploading long video ({size / 1e6:.0f} MB) in chunks")
    s = _fb_post(url, {"access_token": _tok(), "upload_phase": "start", "file_size": str(size)}, timeout=120)
    session, start, end = s["upload_session_id"], int(s["start_offset"]), int(s["end_offset"])
    with open(path, "rb") as fh:
        while start < end:
            fh.seek(start)
            chunk = fh.read(end - start)
            t = _fb_post(url, {"access_token": _tok(), "upload_phase": "transfer",
                               "upload_session_id": session, "start_offset": str(start)},
                         files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")}, timeout=900)
            start, end = int(t["start_offset"]), int(t["end_offset"])
    f = _fb_post(url, {"access_token": _tok(), "upload_phase": "finish", "upload_session_id": session,
                       "title": title[:250], "description": description, "published": "true"}, timeout=300)
    vid = s.get("video_id") or f.get("video_id")
    log(f"facebook: long video posted {vid}")
    return vid


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
