# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A two-stage CLI pipeline that turns a text prompt into a TikTok-ready 9:16 image and publishes it to a CDN:

1. `tiktok_image_generator.py` — prompt → TokenRouter image model → 9:16 PNG saved to disk
2. `imagekit_uploader.py` — local image → ImageKit upload → public CDN URL

The two stages are independent modules but the generator can chain into the uploader via `--upload` (it imports `upload_image` lazily inside the CLI handler).

## Commands

```bash
pip install requests pillow            # only third-party runtime deps

# Generate (auto-named PNG under tiktok_output/)
python tiktok_image_generator.py "a cat smiling wearing red boots"

# Generate + upload in one shot
python tiktok_image_generator.py "neon skyline" --out skyline.png --upload --folder /tiktok

# Use a reference image (face / product / logo preservation)
python tiktok_image_generator.py "wearing a santa hat" --ref ./face.jpg --ref-kind preserve

# Upload existing image(s)
python imagekit_uploader.py img.png --folder /tiktok
python imagekit_uploader.py *.jpg --folder /gallery --json
```

There is no test suite, linter config, or build step in this repo.

## Required environment

Read from env (or a `.env` file — note `.env` is gitignored and holds live secrets):

- `TOKENROUTER_API_KEY` — generator
- `IMAGEKIT_PRIVATE_KEY` — uploader (ImageKit Basic auth: private key as username, empty password)
- `IMAGEKIT_PUBLIC_KEY` — uploader

`.env` loading is NOT automatic in code — export the vars or `source .env` yourself before running.

## Architecture notes that aren't obvious from a single file

**TokenRouter is OpenAI-compatible but images come back over the chat endpoint.** `generate_image` POSTs to `/v1/chat/completions` with `modalities: ["image","text"]`; the image is a base64 data URL buried in `choices[0].message.images[0].image_url.url`. `_extract_data_url` defensively walks several possible response shapes (top-level `images`, or `image_url` parts inside a list `content`) because the exact shape varies by model. `_decode_data_url` also handles the case where a model returns a plain `http(s)` URL instead of a data URL.

**Model capability is gated by frozensets, not flags.** `NATIVE_PORTRAIT_MODELS` (Gemini 3.x) return ~9:16 directly so `_resize_for_tiktok` skips cropping when the source aspect is already within 0.02 of target. `REFERENCE_IMAGE_MODELS` gates the `--ref` feature — passing a reference to a non-listed model raises `ImageGenError`. When changing the default model or adding a model, update these sets.

**Aspect ratio is requested two ways** because the endpoint has no reliable size param: the prompt template (`TIKTOK_PROMPT_TEMPLATE`) asks for 9:16 in natural language, and the payload also sends `aspect_ratio`/`size` hints that non-native models silently ignore. The Pillow `_resize_for_tiktok` step is the actual guarantee of 1080x1920 output (`fit` center-crops, `pad` letterboxes, `none` skips).

**Reference images have two intents.** `--ref-kind preserve` (default) keeps the subject visually identical (faces, branded products); `feature` places the subject into a new scene. These map to two different prompt templates (`REF_PRESERVE_PROMPT_TEMPLATE` / `REF_FEATURE_PROMPT_TEMPLATE`). References are downscaled to `MAX_REF_IMAGE_DIM` (1024) and re-encoded JPEG q90 before sending.

**Errors are funneled through module-specific exceptions** (`ImageGenError`, `ImageKitError`); CLIs catch these and return non-zero. `upload_images` (batch) deliberately does NOT raise — it collects per-file `{"status": "success"|"failed"}` so one bad file doesn't abort the batch.

## Stale docs warning

`TIKTOK_SETUP.md` and `TIKTOK_WORKFLOW_COMPLETE.md` describe an older batch-generator (`test_tiktok_generator.py`, metadata.tsv, Anthropic caption generation, "Sasha Bytes" overlay) that does NOT exist in this repo. Treat README.md as the source of truth; ignore those two files unless explicitly working on that legacy flow.
