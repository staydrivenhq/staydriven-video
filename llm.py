"""Text AI (Gemini free / Anthropic). Google Search grounding diye real research."""
import json
import os
import re
import time

import requests

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def log(msg):
    print("WRITER | " + msg, flush=True)


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


def _gemini_call(model, prompt, json_mode=False, grounding=False, temperature=0.95):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if grounding:
        body["tools"] = [{"google_search": {}}]
    r = requests.post(GEMINI.format(model=model), json=body, timeout=240,
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    cand = r.json()["candidates"][0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text.strip():
        raise RuntimeError("empty answer")
    return text


def ask(cfg, prompt, json_mode=False, grounding=False, temperature=0.95):
    """Prompt pathay; kaj na korle porer model e try kore."""
    if cfg.get("llm_provider") == "anthropic" and os.environ.get("ANTHROPIC_API_KEY") and not grounding:
        for attempt in range(3):
            try:
                r = requests.post("https://api.anthropic.com/v1/messages", timeout=300, headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                    "content-type": "application/json"},
                    json={"model": cfg["anthropic_model"], "max_tokens": 8000, "temperature": temperature,
                          "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json()["content"])
            except Exception as e:
                log(f"anthropic retry {attempt + 1}: {e}")
                time.sleep(10)
    last = None
    for model in cfg["gemini_text_models"]:
        for attempt in range(3):
            try:
                return _gemini_call(model, prompt, json_mode, grounding, temperature)
            except Exception as e:
                last = f"{model}: {e}"
                log("retry | " + last[:220])
                if "404" in str(e) or "400" in str(e):
                    break
                time.sleep(15 * (attempt + 1))
    raise RuntimeError("All text models failed. Last: " + str(last))
