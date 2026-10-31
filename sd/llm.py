"""Text AI for scripts. Tries, in order, until one answers:
   1) Gemini (free)          - GEMINI_API_KEY
   2) Groq (free, no card)   - GROQ_API_KEY
   3) Cloudflare Workers AI  - CF_ACCOUNT_ID + CF_API_TOKEN
   (Anthropic first, only if llm_provider: "anthropic" and ANTHROPIC_API_KEY is set.)
Google Search research (grounding) works only on Gemini; if Gemini is down the script is written
without research notes."""
import json
import os
import re
import time

import requests

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Groq free tier (Llama chat models were retired for free users on 2026-08-16)
GROQ_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"]
CF_MODELS = ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-3.1-8b-instruct"]
DEAD = set()          # models that said "daily quota used up" in this run: skip them


def log(msg):
    print("WRITER | " + msg, flush=True)


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()     # reasoning models
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


class Busy(Exception):
    """Temporary: overloaded / rate limited. Worth one more try later."""


class Dead(Exception):
    """This model can't be used now (quota used up, model gone, bad request)."""


def _check(r, name):
    if r.status_code == 200:
        return
    msg = r.text[:300]
    if r.status_code == 429 and re.search(r"quota|per day|PerDay|daily|exceeded", msg, re.I):
        DEAD.add(name)
        raise Dead(f"{name}: daily quota used up")
    if r.status_code in (429, 500, 502, 503, 504):
        raise Busy(f"{name}: HTTP {r.status_code}")
    DEAD.add(name)
    raise Dead(f"{name}: HTTP {r.status_code} {msg[:160]}")


# ---------------- providers ----------------
def _gemini(model, prompt, json_mode, grounding, temperature):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if grounding:
        body["tools"] = [{"google_search": {}}]
    r = requests.post(GEMINI.format(model=model), json=body, timeout=180,
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    _check(r, "gemini/" + model)
    cand = r.json()["candidates"][0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text.strip():
        raise Busy("gemini: empty answer")
    return text


def _openai_style(url, key, model, name, prompt, json_mode, temperature, extra=None):
    body = {"model": model, "temperature": min(temperature, 1.0), "max_tokens": 7000,
            "messages": [{"role": "user", "content": prompt + ("\n\nAnswer with the JSON only." if json_mode else "")}]}
    body.update(extra or {})
    # No strict JSON mode: some servers reject a long answer over one small JSON slip.
    # extract_json() cleans and parses the answer instead.
    r = requests.post(url, json=body, timeout=240, headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 400 and extra and any(k in r.text for k in extra):
        for k in extra:
            body.pop(k, None)                  # server does not know an optional setting: drop it
        r = requests.post(url, json=body, timeout=240, headers={"Authorization": f"Bearer {key}"})
    _check(r, name)
    text = r.json()["choices"][0]["message"]["content"] or ""
    if not text.strip():
        raise Busy(f"{name}: empty answer")
    return text


def _groq(model, prompt, json_mode, temperature):
    extra = {}
    if "gpt-oss" in model:
        extra = {"reasoning_effort": "low"}          # less thinking = more room for the script
    elif "qwen" in model:
        extra = {"reasoning_format": "hidden"}       # no <think> text in the answer
    return _openai_style("https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"],
                         model, "groq/" + model, prompt, json_mode, temperature, extra)


def _cloudflare(model, prompt, json_mode, temperature):
    acc = os.environ["CF_ACCOUNT_ID"]
    return _openai_style(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/v1/chat/completions",
                         os.environ["CF_API_TOKEN"], model, "cf/" + model, prompt, json_mode, temperature)


def _anthropic(cfg, prompt, temperature):
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=300, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"},
        json={"model": cfg["anthropic_model"], "max_tokens": 8000, "temperature": temperature,
              "messages": [{"role": "user", "content": prompt}]})
    _check(r, "anthropic")
    return "".join(b.get("text", "") for b in r.json()["content"])


def _candidates(cfg, prompt, json_mode, grounding, temperature):
    """(name, function) list in the order to try."""
    c = []
    if cfg.get("llm_provider") == "anthropic" and os.environ.get("ANTHROPIC_API_KEY") and not grounding:
        c.append(("anthropic", lambda: _anthropic(cfg, prompt, temperature)))
    if os.environ.get("GEMINI_API_KEY"):
        for m in cfg.get("gemini_text_models", []):
            c.append(("gemini/" + m, lambda m=m: _gemini(m, prompt, json_mode, grounding, temperature)))
    if grounding:
        return c                      # research needs Google Search: Gemini only
    if os.environ.get("GROQ_API_KEY"):
        for m in cfg.get("groq_models", GROQ_MODELS):
            c.append(("groq/" + m, lambda m=m: _groq(m, prompt, json_mode, temperature)))
    if os.environ.get("CF_ACCOUNT_ID") and os.environ.get("CF_API_TOKEN"):
        for m in cfg.get("cloudflare_models", CF_MODELS):
            c.append(("cf/" + m, lambda m=m: _cloudflare(m, prompt, json_mode, temperature)))
    return c


def ask(cfg, prompt, json_mode=False, grounding=False, temperature=0.95):
    """Tries every provider/model. Busy ones get a second chance after a short wait."""
    cands = _candidates(cfg, prompt, json_mode, grounding, temperature)
    if not cands:
        raise RuntimeError("No text AI key set (GEMINI_API_KEY / GROQ_API_KEY / CF_*)")
    last = "none"
    for rnd in range(3):                      # round 0: everyone once; rounds 1-2: busy ones again
        busy = 0
        for name, fn in cands:
            if name in DEAD:
                continue
            try:
                text = fn()
                if rnd or name != cands[0][0]:
                    log(f"answered by {name}")
                return text
            except Busy as e:
                busy += 1
                last = str(e)
                log("busy | " + last[:160])
                time.sleep(4)
            except Dead as e:
                last = str(e)
                log("skip | " + last[:200])
            except Exception as e:            # network error, bad JSON from server
                busy += 1
                last = f"{name}: {str(e)[:160]}"
                log("error | " + last)
        if not busy:
            break
        time.sleep(45 * (rnd + 1))
    raise RuntimeError("All text AIs failed. Last: " + last)
