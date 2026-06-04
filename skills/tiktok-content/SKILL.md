---
name: tiktok-content
description: From a topic/idea, generate the full text package for one TikTok post in a single Claude call — an image-generation prompt, a caption, a description, and hashtags (returned as JSON). Use when an agent needs post copy plus a ready-to-render image prompt, optionally in a specific persona's voice. Requires TOKENROUTER_API_KEY.
---

# TikTok Content Generator

Turns a topic/idea into everything text/prompt for one post, in one call:

- `image_prompt` — a vivid one-line prompt to feed the `tiktok-image` skill
- `caption` — a scroll-stopping line with emojis (no hashtags)
- `description` — one or two plain sentences of context
- `hashtags` — a list of 3–7 hashtag strings

Text-only — it does not generate an image.

## Requirements

- `TOKENROUTER_API_KEY` — from the real environment or a `.env` in the cwd (or next
  to the script). Real env vars take precedence over `.env`.
- `uv` recommended. Script is stdlib-only (no dependencies installed).

## Run

```bash
uv run scripts/content_generator.py "a jade-green matcha latte on white marble" --json
uv run scripts/content_generator.py "morning skincare routine" --persona "Lika, a 22yo Gen Z skincare creator ..." --json
```

`--json` prints the full object; without it you get a readable summary. Without `uv`:
`python3 scripts/content_generator.py "..." --json`.

## Flags

- `topic` (positional) — the topic/idea the post is about.
- `--persona TEXT` — write the caption in this person's voice and keep the
  `image_prompt` scene-focused (their face/identity is fixed later by a reference
  image at generation time).
- `--model ID` — TokenRouter model id (default `anthropic/claude-haiku-4.5`).
- `--json` — print the full JSON object.

## Output & errors

Returns `{image_prompt, caption, description, hashtags}` — feed `image_prompt` to the
`tiktok-image` skill, and carry `caption`/`description`/`hashtags` through to
`tiktok-publish`. The parser tolerates markdown fences / stray prose and normalizes
hashtags to `#tag` strings. Exits non-zero on missing key, API error, or output that
lacks an `image_prompt`/`caption`.
