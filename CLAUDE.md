# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI pipeline that turns an AI-invented idea into a TikTok-ready 9:16 image, uploads it to ImageKit, and records the post in Airtable. `tiktok_pipeline.py` is the top-level orchestrator; the other modules are independent, individually-runnable stages it chains together via lazy imports:

1. `idea_generator.py` — (optional) theme → Claude on TokenRouter → one-line image idea
2. `caption_generator.py` — idea → Claude on TokenRouter → `{caption, description}` (text-only call, runs BEFORE the image so it can be logged to Airtable)
3. `tiktok_image_generator.py` — prompt → TokenRouter image model → 9:16 PNG in `tiktok_output/`
4. `imagekit_uploader.py` — local image → ImageKit upload → public CDN URL
5. `airtable_logger.py` — idea + caption + ImageKit URL → one record in the Airtable `Posts` table (the downstream tiktok-agent's source of truth)
6. `airtable_migrate.py` — one-time/idempotent additive schema setup for that table (via the Airtable Meta API)

The project has exactly two outputs: **the image on ImageKit** and **a post record in Airtable**. `tiktok_pipeline.py` runs idea → caption → generate → imagekit → airtable. The ImageKit upload is non-fatal (a failure is recorded in the result dict). The Airtable log step is **fatal** (the downstream agent depends on the record). `tiktok_image_generator.py` can also chain straight into the uploader on its own via `--upload`.

All generated images land in one folder (`tiktok_output/`, override with `--output-dir`). The folder is committed via `tiktok_output/.gitkeep`; its image contents are gitignored. Auto-named files follow a consistent, chronologically sortable timestamp format — `tiktok_YYYYMMDD_HHMMSS.<ext>` (built by `_timestamped_path` in `tiktok_image_generator.py`, with a `_N` suffix only on same-second collisions). Passing `--out` overrides the name entirely.

## Commands

This project is managed with **uv**. `uv sync` installs deps from `pyproject.toml` / `uv.lock` into `.venv`. Each module is registered as a console script in `[project.scripts]`, so prefer `uv run <script>` over invoking python directly. Run `uv run airtable-migrate` once to create the Airtable `Posts` table before the first pipeline run.

```bash
uv sync                                # create .venv, install pinned deps

# One-time: create/extend the Airtable Posts table (idempotent, additive)
uv run airtable-migrate

# Fully automatic: AI idea -> image -> ImageKit -> Airtable record
uv run tiktok-pipeline --theme "cyberpunk street food"

# Own prompt (skip the AI idea step)
uv run tiktok-pipeline --prompt "neon skyline"

# As a recurring character (persona + reference-image identity)
uv run tiktok-pipeline --profile kalila --theme "morning skincare routine"

# Generate (auto-named PNG under tiktok_output/)
uv run tiktok-generate "a cat smiling wearing red boots"

# Generate + upload in one shot
uv run tiktok-generate "neon skyline" --out skyline.png --upload --folder /tiktok

# Use a reference image (face / product / logo preservation)
uv run tiktok-generate "wearing a santa hat" --ref ./face.jpg --ref-kind preserve

# Upload existing image(s)
uv run imagekit-upload img.png --folder /tiktok
uv run imagekit-upload *.jpg --folder /gallery --json

# Write a single Airtable record by hand (testing the logger)
uv run airtable-log --idea "a cat in red boots" --caption "..." --image-url https://ik.imagekit.io/salt/x.png
```

Console-script → module map (in `pyproject.toml`): `tiktok-pipeline`→`tiktok_pipeline`, `tiktok-generate`→`tiktok_image_generator`, `tiktok-idea`→`idea_generator`, `tiktok-caption`→`caption_generator`, `tiktok-profile`→`profile_loader`, `imagekit-upload`→`imagekit_uploader`, `airtable-log`→`airtable_logger`, `airtable-migrate`→`airtable_migrate` (each points at the module's `_cli`). Adding a dependency: `uv add <pkg>` (updates `pyproject.toml` + `uv.lock`). There is no test suite or linter config in this repo.

## Required environment

Read from env (or a `.env` file — note `.env` is gitignored and holds live secrets):

- `TOKENROUTER_API_KEY` — **both** the idea step and image generation (idea uses an Anthropic model served through TokenRouter's OpenAI-compatible endpoint, so there is NO separate `ANTHROPIC_API_KEY` and no `anthropic` SDK dependency)
- `IMAGEKIT_PRIVATE_KEY` — uploader (ImageKit Basic auth: private key as username, empty password)
- `IMAGEKIT_PUBLIC_KEY` — uploader
- `AIRTABLE_API_KEY` — Airtable logger + migrate (Bearer personal access token; `data.records:write` for the logger, plus `schema.bases:write` for `airtable-migrate`)
- `AIRTABLE_BASE_ID` — Airtable base id (`app...`)
- `AIRTABLE_TABLE_NAME` — target table (default project value: `Posts`)

A local `.env` is loaded automatically: every module's `_cli()` calls `env_loader.load_env()` (a zero-dependency loader in `env_loader.py`) before parsing args, so you don't need to `source .env`. Real environment variables take precedence over `.env` values (`override=False`); the loader looks for `.env` next to the module first, then the cwd. Idea model ids use the `anthropic/` prefix on TokenRouter (default `anthropic/claude-haiku-4.5`); image model ids use `google/...` or `openai/...`.

## Architecture notes that aren't obvious from a single file

**TokenRouter is OpenAI-compatible but images come back over the chat endpoint.** `generate_image` POSTs to `/v1/chat/completions` with `modalities: ["image","text"]`; the image is a base64 data URL buried in `choices[0].message.images[0].image_url.url`. `_extract_data_url` defensively walks several possible response shapes (top-level `images`, or `image_url` parts inside a list `content`) because the exact shape varies by model. `_decode_data_url` also handles the case where a model returns a plain `http(s)` URL instead of a data URL.

**Model capability is gated by frozensets, not flags.** `NATIVE_PORTRAIT_MODELS` (Gemini 3.x) return ~9:16 directly so `_resize_for_tiktok` skips cropping when the source aspect is already within 0.02 of target. `REFERENCE_IMAGE_MODELS` gates the `--ref` feature — passing a reference to a non-listed model raises `ImageGenError`. When changing the default model or adding a model, update these sets.

**Refusals are retried; other errors fail fast.** `_extract_data_url` raises `ImageRefusal` (a retryable `ImageGenError` subclass) when the response has no image — either an explicit `refusal` field or empty content. `generate_image` retries on `ImageRefusal` (`retries`, default 2; `--retries` on the generator and pipeline), but HTTP/network/JSON errors fail immediately. Refusals are common on reference-image edits of real faces, so a profile run that fails once often succeeds on retry. Reference images are sent at ≤`MAX_REF_IMAGE_DIM` (1024px, JPEG q90) regardless of on-disk size, so source-image resolution does not change generation cost.

**Aspect ratio is requested two ways** because the endpoint has no reliable size param: the prompt template (`TIKTOK_PROMPT_TEMPLATE`) asks for 9:16 in natural language, and the payload also sends `aspect_ratio`/`size` hints that non-native models silently ignore. The Pillow `_resize_for_tiktok` step is the actual guarantee of 1080x1920 output (`fit` center-crops, `pad` letterboxes, `none` skips).

**Reference images have two intents.** `--ref-kind preserve` (default) keeps the subject visually identical (faces, branded products); `feature` places the subject into a new scene. These map to two different prompt templates (`REF_PRESERVE_PROMPT_TEMPLATE` / `REF_FEATURE_PROMPT_TEMPLATE`). References are downscaled to `MAX_REF_IMAGE_DIM` (1024) and re-encoded JPEG q90 before sending.

**Errors are funneled through module-specific exceptions** (`ImageGenError`, `ImageKitError`, `IdeaError`, `AirtableError`); CLIs catch these and return non-zero. `upload_image` and the pipeline's ImageKit step deliberately do NOT abort the run — the ImageKit failure is collected as `{"status": "failed", ...}`. `airtable_logger.create_record` is the exception: it DOES raise, because the Airtable step is fatal.

**The pipeline isolates the ImageKit failure but treats Airtable as fatal.** `run_pipeline` (`tiktok_pipeline.py`) treats the idea, image-generation, and Airtable-logging steps as fatal, but wraps the caption step and the ImageKit upload in their own try/except. It returns a result dict with per-step status; the CLI exits non-zero if the ImageKit upload failed, or if the Airtable write raised (which propagates out of `run_pipeline` to the CLI's catch-all → exit 1).

**Caption/description hand-off via an Airtable record (NOT ImageKit metadata).** The caption step runs before image generation; after the ImageKit upload, `run_pipeline` calls `airtable_logger.create_record(...)` with the idea, caption, description, ImageKit URL + fileId, local path, profile, and `Status="pending"`. The downstream tiktok-agent (separate repo, see [[tiktok-two-repo-architecture]]) reads `Status="pending"` rows from Airtable, posts them, and flips `Status` to mark them done — it no longer reads ImageKit custom metadata, and the pipeline no longer writes any (`upload_image` is called without `custom_metadata`). The table/fields are created once with `airtable-migrate`. The Airtable Meta API is **additive only**: `airtable_migrate.py` can create the table and add missing fields but cannot delete, rename, or retype a field (do those by hand in the Airtable UI). `create_record` sends `typecast: true` so string values coerce into the right field types.

**Profiles = recurring character (persona + reference images).** `--profile <name>` loads `profiles/<name>/profile.json` via `profile_loader.load_profile`. The profile supplies (1) `reference_paths` (the listed `reference_images`, resolved/verified) which override any `--ref` and are passed to `generate_image` to preserve the person's identity (`reference_kind` defaults to `preserve`), and (2) a `persona` string — `profile_loader._build_persona` folds the demographic fields + `content_pillars` into it — threaded into `generate_idea(persona=...)` and `generate_caption(persona=...)`. When a persona is present, `idea_generator` switches to `_PERSONA_SYSTEM_PROMPT`, which describes the SCENE/pose/wardrobe (not facial features, since identity is fixed by the reference). The default image model (`gemini-3.1-flash-image-preview`) is in `REFERENCE_IMAGE_MODELS`, so reference images work out of the box.
