---
name: tiktok-pipeline
description: Run the full TikTok content pipeline end-to-end — AI invents an idea, writes a caption, an image model renders a 9:16 image, it is uploaded to ImageKit, and a post record is written to Airtable. Use when an agent should produce a complete, published TikTok post in one shot, optionally as a recurring character via a profile. Requires TOKENROUTER_API_KEY, IMAGEKIT_PRIVATE_KEY, and the AIRTABLE_* variables.
---

# TikTok Pipeline (orchestrator)

Chains the individual stages: profile → idea → caption → image → ImageKit → Airtable.
The two outputs are the image on ImageKit and a post record in Airtable. The ImageKit
upload is non-fatal (its failure is captured in the result); the Airtable write is
fatal. This skill bundles every stage, so it runs standalone.

## Requirements

- `TOKENROUTER_API_KEY` — idea, caption, and image generation.
- `IMAGEKIT_PRIVATE_KEY` — ImageKit upload (unless `--no-imagekit`).
- `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME` — Airtable record
  (unless `--no-airtable`). Run the `airtable-migrate` skill once first to create the
  table.
- Credentials from the real environment or a `.env` in the cwd (or next to the script).
- `uv` recommended — the inline PEP 723 header auto-installs `pillow` + `requests`.

## Run

```bash
# Fully automatic: AI idea -> image -> ImageKit -> Airtable
uv run scripts/tiktok_pipeline.py --theme "cyberpunk street food"

# Own prompt (skip the AI idea step)
uv run scripts/tiktok_pipeline.py --prompt "neon skyline"

# As a recurring character (persona + reference-image identity)
uv run scripts/tiktok_pipeline.py --profile kalila --theme "morning skincare routine" --profiles-dir ./profiles
```

Without `uv`: `pip install pillow requests` then `python3 scripts/tiktok_pipeline.py ...`.

## Key flags

- `--prompt TEXT` — use an exact prompt instead of an AI idea.
- `--theme TEXT` — theme to steer the AI idea (ignored if `--prompt` is set).
- `--model ID` — TokenRouter image model.
- `--idea-model ID`, `--caption-model ID` — Anthropic models (default `anthropic/claude-haiku-4.5`).
- `--no-caption` — skip caption/description generation.
- `--out, -o PATH`, `--output-dir DIR` — image output path / folder.
- `--resize fit|pad|none`, `--width N`, `--height N` — resize strategy / target size.
- `--ref PATH_OR_URL`, `--ref-kind preserve|feature` — reference-image identity.
- `--retries N` — extra image attempts on refusal (default 2).
- `--profile NAME`, `--profiles-dir DIR` — recurring character (persona + reference images).
- `--seed N` — reproducible outfit/setting/pose pick.
- `--no-imagekit`, `--folder PATH` — skip / target the ImageKit upload.
- `--no-airtable` — skip the Airtable record.

## Profiles

`--profile NAME` loads `profiles/<NAME>/profile.json` (from `--profiles-dir`, default
`profiles/`). It supplies the persona (threaded into idea + caption) and reference
images (preserve the character's identity). See
[refs/PROFILE_SCHEMA.md](refs/PROFILE_SCHEMA.md) for the schema and a template. You
provide your own profiles directory.

## Output & errors

Returns a result dict with per-step status (`idea`, `caption`, `description`, `path`,
`imagekit`, `airtable`). Exits non-zero if the ImageKit upload failed or the Airtable
write raised; idea and image generation are also fatal.
