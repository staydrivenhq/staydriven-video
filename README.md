# Stay Driven Autopilot

Daily cinematic motivation videos, made and posted automatically (free):

- **Long** (6-8 min, 1920x1080) → YouTube + Facebook Page — 10:41 UTC
- **Short/Reel** (40-55 s, 1080x1920, with voice) → YouTube Shorts + Facebook Reels + Instagram Reels — 22:41 UTC

Pipeline: Gemini research + script → Gemini voice (Edge fallback) → word timing (faster-whisper)
→ Pexels/Pixabay footage → color grade, drift, grain, kinetic captions, original score + SFX
→ thumbnail → YouTube (token from the channel's own Apps Script) / Facebook / Instagram.

Setup: follow the "Stay Driven Autopilot — Setup Guide" doc step by step.
Settings: `config.yaml`. Schedule: `.github/workflows/daily.yml`.

Folders: `sd/` engine · `apps-script/` YouTube token helper · `music/` your royalty-free tracks
· `fonts/` Anton + Bebas Neue (SIL OFL) · `data/history.json` memory (no repeats).
