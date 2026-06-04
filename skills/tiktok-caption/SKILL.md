---
name: tiktok-caption
description: Write a TikTok caption and a longer description for a given image concept using an Anthropic model on TokenRouter. Returns a JSON object {caption, description}. Use when an agent needs post copy to accompany an image, optionally in a specific persona's voice. Requires TOKENROUTER_API_KEY.
---

# TikTok Caption Generator

Given an image concept (a subject/idea string), produces the post text: a short
`caption` and a longer `description`. Text-only call — no image is generated.

## Requirements

- `TOKENROUTER_API_KEY` — from the real environment or a `.env` in the cwd (or next
  to the script). Real env vars take precedence over `.env`.
- `uv` recommended. Script is stdlib-only (no dependencies installed).

## Run

```bash
uv run scripts/caption_generator.py "a cat smiling wearing red boots" --json
```

`--json` prints the full `{"caption": ..., "description": ...}` object. Without
`--json` it prints formatted text. Without `uv`:

```bash
python3 scripts/caption_generator.py "a cat ..." --json
```

## Flags

- `subject` (positional) — the image concept the post is about.
- `--model ID` — TokenRouter model id (default `anthropic/claude-haiku-4.5`).
- `--json` — print the full JSON object instead of formatted text.

## Output & errors

Returns `{caption, description}`. The JSON is tolerant of markdown fences / stray
prose in the model reply. Exits non-zero on missing key, API error, or output that
cannot be parsed into the two keys.
