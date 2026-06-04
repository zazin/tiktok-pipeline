# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI pipeline that turns an AI-invented idea into a TikTok-ready 9:16 image and delivers it to two targets. `tiktok_pipeline.py` is the top-level orchestrator; the other modules are independent, individually-runnable stages it chains together via lazy imports:

1. `idea_generator.py` — (optional) theme → Claude on TokenRouter → one-line image idea
2. `tiktok_image_generator.py` — prompt → TokenRouter image model → 9:16 PNG in `tiktok_output/`
3. `phone_uploader.py` — local image → Android phone over USB (adb push)
4. `imagekit_uploader.py` — local image → ImageKit upload → public CDN URL

`tiktok_pipeline.py` runs idea → generate → (phone AND imagekit). The two delivery targets are independent and non-fatal: a failure in one is recorded and reported but does not abort the other or the run. `tiktok_image_generator.py` can also chain straight into the uploader on its own via `--upload`.

All generated images land in one folder (`tiktok_output/`, override with `--output-dir`). The folder is committed via `tiktok_output/.gitkeep`; its image contents are gitignored.

## Commands

This project is managed with **uv**. `uv sync` installs deps from `pyproject.toml` / `uv.lock` into `.venv`. Each module is registered as a console script in `[project.scripts]`, so prefer `uv run <script>` over invoking python directly. `adb` (separate, `brew install android-platform-tools`) is needed only for phone delivery.

```bash
uv sync                                # create .venv, install pinned deps

# Fully automatic: AI idea -> image -> phone + ImageKit
uv run tiktok-pipeline --theme "cyberpunk street food"

# Own prompt, ImageKit only (no phone)
uv run tiktok-pipeline --prompt "neon skyline" --no-phone

# Generate (auto-named PNG under tiktok_output/)
uv run tiktok-generate "a cat smiling wearing red boots"

# Generate + upload in one shot
uv run tiktok-generate "neon skyline" --out skyline.png --upload --folder /tiktok

# Use a reference image (face / product / logo preservation)
uv run tiktok-generate "wearing a santa hat" --ref ./face.jpg --ref-kind preserve

# Upload existing image(s)
uv run imagekit-upload img.png --folder /tiktok
uv run imagekit-upload *.jpg --folder /gallery --json
```

Console-script → module map (in `pyproject.toml`): `tiktok-pipeline`→`tiktok_pipeline`, `tiktok-generate`→`tiktok_image_generator`, `tiktok-idea`→`idea_generator`, `imagekit-upload`→`imagekit_uploader`, `phone-upload`→`phone_uploader` (each points at the module's `_cli`). Adding a dependency: `uv add <pkg>` (updates `pyproject.toml` + `uv.lock`). There is no test suite or linter config in this repo.

## Required environment

Read from env (or a `.env` file — note `.env` is gitignored and holds live secrets):

- `TOKENROUTER_API_KEY` — **both** the idea step and image generation (idea uses an Anthropic model served through TokenRouter's OpenAI-compatible endpoint, so there is NO separate `ANTHROPIC_API_KEY` and no `anthropic` SDK dependency)
- `IMAGEKIT_PRIVATE_KEY` — uploader (ImageKit Basic auth: private key as username, empty password)
- `IMAGEKIT_PUBLIC_KEY` — uploader

A local `.env` is loaded automatically: every module's `_cli()` calls `env_loader.load_env()` (a zero-dependency loader in `env_loader.py`) before parsing args, so you don't need to `source .env`. Real environment variables take precedence over `.env` values (`override=False`); the loader looks for `.env` next to the module first, then the cwd. Idea model ids use the `anthropic/` prefix on TokenRouter (default `anthropic/claude-haiku-4.5`); image model ids use `google/...` or `openai/...`.

## Architecture notes that aren't obvious from a single file

**TokenRouter is OpenAI-compatible but images come back over the chat endpoint.** `generate_image` POSTs to `/v1/chat/completions` with `modalities: ["image","text"]`; the image is a base64 data URL buried in `choices[0].message.images[0].image_url.url`. `_extract_data_url` defensively walks several possible response shapes (top-level `images`, or `image_url` parts inside a list `content`) because the exact shape varies by model. `_decode_data_url` also handles the case where a model returns a plain `http(s)` URL instead of a data URL.

**Model capability is gated by frozensets, not flags.** `NATIVE_PORTRAIT_MODELS` (Gemini 3.x) return ~9:16 directly so `_resize_for_tiktok` skips cropping when the source aspect is already within 0.02 of target. `REFERENCE_IMAGE_MODELS` gates the `--ref` feature — passing a reference to a non-listed model raises `ImageGenError`. When changing the default model or adding a model, update these sets.

**Aspect ratio is requested two ways** because the endpoint has no reliable size param: the prompt template (`TIKTOK_PROMPT_TEMPLATE`) asks for 9:16 in natural language, and the payload also sends `aspect_ratio`/`size` hints that non-native models silently ignore. The Pillow `_resize_for_tiktok` step is the actual guarantee of 1080x1920 output (`fit` center-crops, `pad` letterboxes, `none` skips).

**Reference images have two intents.** `--ref-kind preserve` (default) keeps the subject visually identical (faces, branded products); `feature` places the subject into a new scene. These map to two different prompt templates (`REF_PRESERVE_PROMPT_TEMPLATE` / `REF_FEATURE_PROMPT_TEMPLATE`). References are downscaled to `MAX_REF_IMAGE_DIM` (1024) and re-encoded JPEG q90 before sending.

**Errors are funneled through module-specific exceptions** (`ImageGenError`, `ImageKitError`); CLIs catch these and return non-zero. `upload_images` (batch) deliberately does NOT raise — it collects per-file `{"status": "success"|"failed"}` so one bad file doesn't abort the batch.

## Stale docs warning

`TIKTOK_SETUP.md` and `TIKTOK_WORKFLOW_COMPLETE.md` describe an older batch-generator (`test_tiktok_generator.py`, metadata.tsv, Anthropic caption generation, "Sasha Bytes" overlay) that does NOT exist in this repo. Treat README.md as the source of truth; ignore those two files unless explicitly working on that legacy flow.
