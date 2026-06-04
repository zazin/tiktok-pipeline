---
name: tiktok-image
description: Generate a TikTok-ready 9:16 image (1080x1920) from a text prompt via a TokenRouter image model, with optional reference-image identity preservation (including multi-angle avatar faces). Saves a PNG locally — it does not upload or record anywhere. Use when an agent needs to render a vertical portrait image from a prompt. Requires TOKENROUTER_API_KEY.
---

# TikTok Image Generator

Renders a vertical 9:16 image from a text prompt, saving a PNG under
`tiktok_output/` (auto-named `tiktok_YYYYMMDD_HHMMSS.png`) or a path you choose.
Pillow guarantees the final 1080x1920 size (center-crop, letterbox, or none). This
skill only generates the image — to publish it, pass the saved file to the
`tiktok-upload` skill (ImageKit upload + Airtable record).

## Requirements

- `TOKENROUTER_API_KEY` — image generation.
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `pillow`.

## Run

```bash
uv run scripts/tiktok_image_generator.py "a cat smiling wearing red boots"
uv run scripts/tiktok_image_generator.py "neon skyline" --out skyline.png
uv run scripts/tiktok_image_generator.py "wearing a santa hat" --ref ./face.jpg --ref-kind preserve
```

Without `uv`: `pip install pillow` then
`python3 scripts/tiktok_image_generator.py "..."`.

## Flags

- `prompt` (positional) — the text idea.
- `--out, -o PATH` — output file (default: auto-named under `tiktok_output/`).
- `--model ID` — TokenRouter image model (default `google/gemini-3.1-flash-image-preview`).
- `--raw-prompt` — use the prompt as-is, skip the 9:16 style template.
- `--retries N` — extra attempts on a refusal / no-image response (default 2).
- `--resize fit|pad|none` — `fit` center-crops (default), `pad` letterboxes, `none` skips.
- `--width N`, `--height N` — target resolution (default 1080x1920).
- `--ref PATH_OR_URL` — reference image (local path, http(s), or data: URL).
  **Repeatable**: pass `--ref` several times to give multiple angles of the same
  subject (e.g. a multi-angle avatar face) for stronger identity preservation.
- `--ref-kind preserve|feature` — `preserve` keeps the subject identical (faces,
  products); `feature` places the subject into a new scene. Default `preserve`.

## Avatar / reference images

The avatar face photos are **the agent's own identity data, not part of this skill**
— skills hold reusable code, not per-character assets. Keep them in the consuming
agent's workspace and pass them at runtime with `--ref`:

```bash
# the agent stores its own avatar angles, e.g. ./avatar/
uv run scripts/tiktok_image_generator.py "at a sunlit cafe, holding a latte" \
  --ref ./avatar/face_front.jpg \
  --ref ./avatar/face_left.jpg \
  --ref ./avatar/face_right.jpg \
  --ref-kind preserve
```

You can also host the angles once (e.g. on ImageKit) and pass `--ref https://...`
URLs instead of local files — handy when the same avatar is reused across runs.

## Output & errors

Prints `Saved: <path>` — the local PNG path. Hand that path to the `tiktok-upload`
skill to publish it. Reference images only work with reference-capable models (the
default model is one); they are downscaled to 1024px JPEG before sending, so source
resolution doesn't change cost. Refusals (common when editing real faces) are retried
per `--retries`; HTTP / network errors fail fast. Exits non-zero on `ImageGenError`.
