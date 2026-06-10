# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI pipeline that turns an AI-invented idea into a TikTok-ready 9:16 image, uploads it to ImageKit, and publishes the post to HiveMQ. `tiktok_pipeline.py` is the top-level orchestrator; the other modules are independent, individually-runnable stages it chains together via lazy imports:

1. `idea_generator.py` — (optional) theme → Claude on TokenRouter → one-line image idea
2. `content_generator.py` — topic → Claude on TokenRouter → `{image_prompt, caption, description, hashtags}` (text-only call; the `image_prompt` feeds image generation, the rest is the post copy). The post copy language is selectable via `--language id|en` (default `id`, Indonesian; `en` for English) on both `tiktok-content` and `tiktok-pipeline` — `image_prompt` always stays English for the image model
3. `tiktok_image_generator.py` — prompt → TokenRouter image model → 9:16 PNG in `tiktok_output/`
4. `imagekit_uploader.py` — local image → ImageKit upload → public CDN URL
5. `hivemq_publisher.py` — idea + caption + ImageKit URL + post fields → one MQTT message on a HiveMQ Cloud topic (the pipeline's hand-off to the downstream tiktok-agent, which subscribes and posts the content)

Separately from the image pipeline, the repo also provides a **comment-on-a-post** tool (`comment_generator.py` + `comment_on_post.py`): AI-write a TikTok comment from a sentiment (e.g. positive/negative) and publish a `{PostURL, Comment}` message to the `tiktok/comments` topic. The downstream tiktok-agent opens the post by URL and leaves the comment (contract: tiktok-agent `docs/comment-on-post.md`). This tool never looks at the post itself — context about the post is an optional `--about` text input.

The pipeline's outputs are **the image on ImageKit** and **a HiveMQ message** describing the post. `tiktok_pipeline.py` runs idea → caption → generate → imagekit → hivemq. The ImageKit upload is non-fatal (a failure is recorded in the result dict). The HiveMQ publish is also non-fatal (recorded in the result dict), but the CLI exits non-zero when it fails since the message is the hand-off. `tiktok_image_generator.py` can also chain straight into the uploader on its own via `--upload`.

All generated images land in one folder (`tiktok_output/`, override with `--output-dir`). The folder is committed via `tiktok_output/.gitkeep`; its image contents are gitignored. Auto-named files follow a consistent, chronologically sortable timestamp format — `tiktok_YYYYMMDD_HHMMSS.<ext>` (built by `_timestamped_path` in `tiktok_image_generator.py`, with a `_N` suffix only on same-second collisions). Passing `--out` overrides the name entirely.

## Commands

This project is managed with **uv**. `uv sync` installs deps from `pyproject.toml` / `uv.lock` into `.venv`. Each module is registered as a console script in `[project.scripts]`, so prefer `uv run <script>` over invoking python directly.

```bash
uv sync                                # create .venv, install pinned deps

# Fully automatic: AI idea -> image -> ImageKit -> HiveMQ
uv run tiktok-pipeline --theme "cyberpunk street food"

# Own prompt (skip the AI idea step)
uv run tiktok-pipeline --prompt "neon skyline"

# Post copy in English (defaults to Indonesian)
uv run tiktok-pipeline --theme "cyberpunk street food" --language en

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

# Publish a single HiveMQ message by hand (testing the publisher)
uv run hivemq-publish --idea "a cat in red boots" --caption "..." --image-url https://ik.imagekit.io/salt/x.png --json

# Comment on an existing post: AI-generate from a sentiment, then publish to tiktok/comments
uv run tiktok-comment https://www.tiktok.com/@user/video/123 --sentiment positive
uv run tiktok-comment <url> --sentiment negative --about "a 12-step skincare routine"
uv run tiktok-comment <url> --comment "Nice video!"      # publish exact text, no AI

# Just generate a comment (no publish)
uv run tiktok-comment-gen positive --about "homemade matcha latte"
```

Console-script → module map (in `pyproject.toml`): `tiktok-pipeline`→`tiktok_pipeline`, `tiktok-generate`→`tiktok_image_generator`, `tiktok-publish`→`tiktok_publish`, `tiktok-idea`→`idea_generator`, `tiktok-content`→`content_generator`, `tiktok-comment`→`comment_on_post`, `tiktok-comment-gen`→`comment_generator`, `tiktok-profile`→`profile_loader`, `imagekit-upload`→`imagekit_uploader`, `hivemq-publish`→`hivemq_publisher` (each points at the module's `_cli`). Adding a dependency: `uv add <pkg>` (updates `pyproject.toml` + `uv.lock`). There is no test suite or linter config in this repo.

## Required environment

Read from env (or a `.env` file — note `.env` is gitignored and holds live secrets):

- `TOKENROUTER_API_KEY` — **both** the idea step and image generation (idea uses an Anthropic model served through TokenRouter's OpenAI-compatible endpoint, so there is NO separate `ANTHROPIC_API_KEY` and no `anthropic` SDK dependency)
- `IMAGEKIT_PRIVATE_KEY` — uploader (ImageKit Basic auth: private key as username, empty password)
- `IMAGEKIT_PUBLIC_KEY` — uploader
- `HIVEMQ_HOST` / `HIVEMQ_USERNAME` / `HIVEMQ_PASSWORD` — HiveMQ publisher (HiveMQ Cloud broker host + credentials; unless `--no-hivemq`)

Optional:

- `IMAGEKIT_URL_ENDPOINT` — public URL endpoint the uploader uses to build the returned image URL (`endpoint` + the uploaded `filePath`). Defaults to `https://ik.imagekit.io/salt/` when unset; a trailing slash is normalized.
- `HIVEMQ_PORT` — HiveMQ broker TLS port. Defaults to `8883` when unset (`DEFAULT_PORT` in `hivemq_publisher.py`).
- `HIVEMQ_TOPIC` — topic to publish to. Defaults to `tiktok/posts` when unset (`DEFAULT_TOPIC` in `hivemq_publisher.py`).
- `HIVEMQ_COMMENT_TOPIC` — topic for the comment-on-a-post tool. Defaults to `tiktok/comments` when unset (`DEFAULT_COMMENT_TOPIC` in `hivemq_publisher.py`).
- `HIVEMQ_CLIENT_ID` — MQTT client id for `publish_post`. Defaults to empty (broker assigns one) when unset. `publish_comment` ignores it and always uses a broker-assigned id, so the comment publisher can never collide with the agent's own client ids (which would disconnect the agent).
- `TIKTOK_ACCOUNT` — optional, the `Account` field on every published post (a TikTok `@handle`, e.g. `@captgani`). The downstream tiktok-agent switches to it before posting; if the account is not active it reports `wrong_account` and does not post (see tiktok-agent `docs/post-image.md`). Set per-run (e.g. `TIKTOK_ACCOUNT=@captgani uv run tiktok-pipeline --profile gani ...`) since this repo only supports one value at a time.

A local `.env` is loaded automatically: every module's `_cli()` calls `env_loader.load_env()` (a zero-dependency loader in `env_loader.py`) before parsing args, so you don't need to `source .env`. Real environment variables take precedence over `.env` values (`override=False`); the loader looks for `.env` next to the module first, then the cwd. Idea model ids use the `anthropic/` prefix on TokenRouter (default `anthropic/claude-haiku-4.5`); image model ids use `google/...` or `openai/...`.

## Architecture notes that aren't obvious from a single file

**TokenRouter is OpenAI-compatible but images come back over the chat endpoint.** `generate_image` POSTs to `/v1/chat/completions` with `modalities: ["image","text"]`; the image is a base64 data URL buried in `choices[0].message.images[0].image_url.url`. `_extract_data_url` defensively walks several possible response shapes (top-level `images`, or `image_url` parts inside a list `content`) because the exact shape varies by model. `_decode_data_url` also handles the case where a model returns a plain `http(s)` URL instead of a data URL.

**Model capability is gated by frozensets, not flags.** `NATIVE_PORTRAIT_MODELS` (Gemini 3.x) return ~9:16 directly so `_resize_for_tiktok` skips cropping when the source aspect is already within 0.02 of target. `REFERENCE_IMAGE_MODELS` gates the `--ref` feature — passing a reference to a non-listed model raises `ImageGenError`. When changing the default model or adding a model, update these sets.

**Refusals are retried; other errors fail fast.** `_extract_data_url` raises `ImageRefusal` (a retryable `ImageGenError` subclass) when the response has no image — either an explicit `refusal` field or empty content. `generate_image` retries on `ImageRefusal` (`retries`, default 2; `--retries` on the generator and pipeline), but HTTP/network/JSON errors fail immediately. Refusals are common on reference-image edits of real faces, so a profile run that fails once often succeeds on retry. Reference images are sent at ≤`MAX_REF_IMAGE_DIM` (1024px, JPEG q90) regardless of on-disk size, so source-image resolution does not change generation cost.

**Aspect ratio is requested two ways** because the endpoint has no reliable size param: the prompt template (`TIKTOK_PROMPT_TEMPLATE`) asks for 9:16 in natural language, and the payload also sends `aspect_ratio`/`size` hints that non-native models silently ignore. The Pillow `_resize_for_tiktok` step is the actual guarantee of 1080x1920 output (`fit` center-crops, `pad` letterboxes, `none` skips).

**Reference images have two intents.** `--ref-kind preserve` (default) keeps the subject visually identical (faces, branded products); `feature` places the subject into a new scene. These map to two different prompt templates (`REF_PRESERVE_PROMPT_TEMPLATE` / `REF_FEATURE_PROMPT_TEMPLATE`). References are downscaled to `MAX_REF_IMAGE_DIM` (1024) and re-encoded JPEG q90 before sending.

**Errors are funneled through module-specific exceptions** (`ImageGenError`, `ImageKitError`, `IdeaError`, `HiveMQError`); CLIs catch these and return non-zero. `upload_image` and the pipeline's ImageKit step deliberately do NOT abort the run — the ImageKit failure is collected as `{"status": "failed", ...}`. The HiveMQ publish step is likewise non-fatal in `run_pipeline` (failure collected in the result dict), though the CLI still exits non-zero when it fails since the message is the hand-off.

**HiveMQ is the pipeline's hand-off to the agent.** After the ImageKit upload, `run_pipeline` (and `tiktok_publish.upload_and_publish`) build a post payload (idea, caption, description, ImageKit URL + fileId, local path, profile, `Status="pending"`) and call `hivemq_publisher.publish_post(...)`, publishing one JSON message to `HIVEMQ_TOPIC` (default `tiktok/posts`) over TLS at QoS 1. The publish is non-fatal (a broker hiccup is recorded in the result dict, not raised), so the image still lands on ImageKit. The publisher uses paho-mqtt's v2 callback API (`CallbackAPIVersion.VERSION2`), connects, `loop_start()`s, publishes, and `wait_for_publish()`s for the broker ack before disconnecting. Durable delivery (so the agent gets a backlog after a disconnect) is the **subscriber's** responsibility — see [[tiktok-two-repo-architecture]] and `docs/hivemq.md`.

**The pipeline isolates ImageKit and HiveMQ failures.** `run_pipeline` (`tiktok_pipeline.py`) treats the idea and image-generation steps as fatal, but wraps the caption step, the ImageKit upload, and the HiveMQ publish in their own try/except. It returns a result dict with per-step status; the CLI exits non-zero if the ImageKit upload failed or the HiveMQ publish failed.

**Caption/description hand-off via the HiveMQ message (NOT ImageKit metadata).** The caption step runs before image generation; after the ImageKit upload, `run_pipeline` publishes a HiveMQ message with the idea, caption, description, ImageKit URL + fileId, local path, profile, and `Status="pending"`. The downstream tiktok-agent (separate repo, see [[tiktok-two-repo-architecture]]) subscribes to the topic and posts the content — it no longer reads ImageKit custom metadata, and the pipeline no longer writes any (`upload_image` is called without `custom_metadata`). The payload field names (`Idea`, `Caption`, `ImageURL`, …) and a `CreatedAt` ISO-8601 UTC timestamp are stamped by `hivemq_publisher.publish_post`.

**Profiles = recurring character (persona + reference images).** `--profile <name>` loads `profiles/<name>/profile.json` via `profile_loader.load_profile`. The profile supplies (1) `reference_paths` (the listed `reference_images`, resolved/verified) which override any `--ref` and are passed to `generate_image` to preserve the person's identity (`reference_kind` defaults to `preserve`), and (2) a `persona` string — `profile_loader._build_persona` folds the demographic fields + `content_pillars` into it — threaded into `generate_idea(persona=...)` and `generate_content(persona=...)`. When a persona is present, `idea_generator` switches to `_PERSONA_SYSTEM_PROMPT`, which describes the SCENE/pose/wardrobe (not facial features, since identity is fixed by the reference). The default image model (`gemini-3.1-flash-image-preview`) is in `REFERENCE_IMAGE_MODELS`, so reference images work out of the box.

**`skills/` packages capabilities as installable Agent Skills (generated, not authored).** The live skills are `tiktok-content` (`content_generator.py` — image prompt + caption + description + hashtags from a topic), `tiktok-image` (generate a PNG only), and `tiktok-publish` (`tiktok_publish.py` — ImageKit upload + HiveMQ publish, which queues the post for the downstream tiktok-agent). `skills/<name>/scripts/` contains COPIES of the root modules — the root modules are the single source of truth, never hand-edit the copies. `skills/sync.sh` regenerates every bundle: it copies each skill's entry module plus the siblings it imports (e.g. `tiktok-publish` bundles `imagekit_uploader.py` + `hivemq_publisher.py`) and prepends a PEP 723 `# /// script` header to the ENTRY copy only, so `uv run skills/<name>/scripts/<entry>.py` auto-installs deps. After changing any root module, run `bash skills/sync.sh`. The `SKILL.md` files and `skills/README.md` are hand-maintained (sync.sh does not touch them). Skills are consumed by external agents via `npx skills add zazin/tiktok-pipeline/skills/<name>`.
