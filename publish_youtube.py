"""YouTube upload. Token ashe channel er nijer Apps Script theke (RelPulse er moto),
tai notun Google Cloud project er 'private lock' er jhamela thake na."""
import json
import os
import time

import requests

from .util import log

UP = "https://www.googleapis.com/upload/youtube/v3"
API = "https://www.googleapis.com/youtube/v3"


def get_token():
    url, key = os.environ.get("SD_TOKEN_URL"), os.environ.get("SD_TOKEN_SECRET")
    if url and key:
        for attempt in range(4):
            try:
                r = requests.get(url, params={"key": key}, timeout=60, allow_redirects=True)
                d = r.json()
                if d.get("ok") and d.get("token"):
                    log(f"youtube: token from Apps Script (channel: {d.get('channel') or '?'})")
                    return d["token"]
                log(f"youtube: Apps Script said: {str(d)[:200]}")
            except Exception as e:
                log(f"youtube: token attempt {attempt + 1} failed: {e}")
            time.sleep(10)
    if os.environ.get("YT_REFRESH_TOKEN"):
        r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
            "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
            "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"})
        r.raise_for_status()
        log("youtube: token from refresh token")
        return r.json()["access_token"]
    raise RuntimeError("No YouTube token: set SD_TOKEN_URL + SD_TOKEN_SECRET")


def upload(path, title, description, tags, cfg, thumb=None, srt=None, comment=None):
    token = get_token()
    H = {"Authorization": f"Bearer {token}"}
    size = os.path.getsize(path)
    status = {"privacyStatus": cfg.get("youtube_privacy", "public"), "selfDeclaredMadeForKids": False,
              "embeddable": True}
    if "youtube_ai_label" in cfg:
        status["containsSyntheticMedia"] = bool(cfg["youtube_ai_label"])
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:20],
                        "categoryId": str(cfg.get("youtube_category_id", "22")), "defaultLanguage": "en",
                        "defaultAudioLanguage": "en"}, "status": status}
    r = requests.post(f"{UP}/videos?uploadType=resumable&part=snippet,status", timeout=60,
                      headers={**H, "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta))
    if r.status_code != 200:
        raise RuntimeError(f"YouTube session failed: {r.status_code} {r.text[:400]}")
    loc = r.headers["Location"]
    chunk = 16 * 1024 * 1024
    pos = 0
    vid = None
    with open(path, "rb") as fh:
        while pos < size:
            fh.seek(pos)
            data = fh.read(chunk)
            end = pos + len(data) - 1
            for attempt in range(6):
                try:
                    rr = requests.put(loc, data=data, timeout=600, headers={
                        **H, "Content-Length": str(len(data)), "Content-Range": f"bytes {pos}-{end}/{size}"})
                    break
                except requests.RequestException as e:
                    log(f"youtube chunk retry {attempt + 1}: {e}")
                    time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError("YouTube upload failed (network)")
            if rr.status_code in (200, 201):
                vid = rr.json()["id"]
                pos = size
            elif rr.status_code == 308:
                rng = rr.headers.get("Range")
                pos = int(rng.split("-")[1]) + 1 if rng else 0
            elif rr.status_code in (500, 502, 503, 504):
                time.sleep(10)
            else:
                raise RuntimeError(f"YouTube upload error {rr.status_code}: {rr.text[:400]}")
    log(f"youtube: uploaded https://youtu.be/{vid}")

    if thumb:
        try:
            t = requests.post(f"{UP}/thumbnails/set?videoId={vid}&uploadType=media", timeout=120,
                              headers={**H, "Content-Type": "image/jpeg"}, data=open(thumb, "rb").read())
            log("youtube: thumbnail " + ("set" if t.ok else f"failed {t.status_code} {t.text[:200]}"))
        except Exception as e:
            log(f"youtube: thumbnail error {e}")
    if srt and cfg.get("youtube_upload_captions", True):
        try:
            boundary = "sdcaptionboundary"
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                    + json.dumps({"snippet": {"videoId": vid, "language": "en", "name": "English",
                                              "isDraft": False}})
                    + f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
                + open(srt, "rb").read() + f"\r\n--{boundary}--".encode()
            c = requests.post(f"{UP}/captions?uploadType=multipart&part=snippet", data=body, timeout=120,
                              headers={**H, "Content-Type": f"multipart/related; boundary={boundary}"})
            log("youtube: captions " + ("added" if c.ok else f"skipped {c.status_code} {c.text[:150]}"))
        except Exception as e:
            log(f"youtube: captions error {e}")
    if comment and cfg.get("youtube_first_comment", True):
        time.sleep(20)
        try:
            c = requests.post(f"{API}/commentThreads?part=snippet", timeout=60, headers=H, json={
                "snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": comment}}}})
            log("youtube: comment " + ("posted" if c.ok else f"skipped {c.status_code} {c.text[:150]}"))
        except Exception as e:
            log(f"youtube: comment error {e}")
    return vid
