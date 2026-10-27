"""EKBAR chalan: Facebook Page token (expire hoy na) + Instagram account ID ber kore.

python tools/get_meta_tokens.py APP_ID APP_SECRET SHORT_USER_TOKEN
"""
import sys

import requests

V = "v23.0"
if len(sys.argv) != 4:
    raise SystemExit(__doc__)
app_id, app_secret, short = sys.argv[1:]

r = requests.get(f"https://graph.facebook.com/{V}/oauth/access_token", timeout=30, params={
    "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
    "fb_exchange_token": short})
r.raise_for_status()
long_user = r.json()["access_token"]

r = requests.get(f"https://graph.facebook.com/{V}/me/accounts", timeout=30, params={
    "access_token": long_user, "fields": "id,name,access_token,instagram_business_account{id,username}"})
r.raise_for_status()
pages = r.json().get("data", [])
if not pages:
    raise SystemExit("Kono Page pawa jayni. Token banano shomoy Page select korechilen?")
for p in pages:
    print("\n==============================")
    print("Page:", p["name"])
    print("FB_PAGE_ID    =", p["id"])
    print("FB_PAGE_TOKEN =", p["access_token"])
    ig = p.get("instagram_business_account")
    if ig:
        print("IG_USER_ID    =", ig["id"], f"(@{ig.get('username')})")
    else:
        print("IG_USER_ID    = (Instagram ei Page er sathe link kora nei, guide Step 6.1 dekhun)")
print("\nStay Driven er value gulo GitHub Secrets e boshan.")
