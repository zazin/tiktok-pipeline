---
name: tiktok-image
description: Generate a TikTok-ready 9:16 image (1080x1920) from a text prompt via a TokenRouter image model, with optional reference-image identity preservation and one-step ImageKit upload. Use when an agent needs to render a vertical portrait image from a prompt. Requires TOKENROUTER_API_KEY (and IMAGEKIT_PRIVATE_KEY only if --upload).
---

# TikTok Image Generator

Renders a vertical 9:16 image from a text prompt, saving a PNG under
`tiktok_output/` (auto-named `tiktok_YYYYMMDD_HHMMSS.png`) or a path you choose.
Pillow guarantees the final 1080x1920 size (center-crop, letterbox, or none). Can
optionally push the result straight to ImageKit and print the public CDN URL.

## Requirements

- `TOKENROUTER_API_KEY` — image generation.
- `IMAGEKIT_PRIVATE_KEY` — only when using `--upload`.
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `pillow` + `requests`.

## Run

```bash
uv run scripts/tiktok_image_generator.py "a cat smiling wearing red boots"
uv run scripts/tiktok_image_generator.py "neon skyline" --out skyline.png --upload --folder /tiktok
uv run scripts/tiktok_image_generator.py "wearing a santa hat" --ref ./face.jpg --ref-kind preserve
```

Without `uv`: `pip install pillow requests` then
`python3 scripts/tiktok_image_generator.py "..."`.

## Flags

- `prompt` (positional) — the text idea.
- `--out, -o PATH` — output file (default: auto-named under `tiktok_output/`).
- `--output-dir DIR` — folder for auto-named files (default `tiktok_output`).
- `--model ID` — TokenRouter image model (default `google/gemini-3.1-flash-image-preview`).
- `--raw-prompt` — use the prompt as-is, skip the 9:16 style template.
- `--retries N` — extra attempts on a refusal / no-image response (default 2).
- `--resize fit|pad|none` — `fit` center-crops (default), `pad` letterboxes, `none` skips.
- `--width N`, `--height N` — target resolution (default 1080x1920).
- `--ref PATH_OR_URL` — reference image (local path, http(s), or data: URL).
- `--ref-kind preserve|feature` — `preserve` keeps the subject identical (faces,
  products); `feature` places the subject into a new scene. Default `preserve`.
- `--upload` — also upload to ImageKit and print the public URL.
- `--folder PATH` — ImageKit folder for `--upload` (default `/tiktok`).

## Notes & errors

Reference images only work with reference-capable models (the default model is one);
they are downscaled to 1024px JPEG before sending, so source resolution doesn't change
cost. Refusals (common when editing real faces) are retried per `--retries`; HTTP /
network errors fail fast. Exits non-zero on `ImageGenError`.
