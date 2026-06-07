# TikTok Image Pipeline

Generate TikTok-ready 9:16 images with AI, upload them to ImageKit CDN, and publish each post to HiveMQ. The whole flow can run fully automatically: an AI invents the image idea, writes a matching caption, an image model renders it, the image is uploaded to ImageKit, and a message describing the post is published to HiveMQ. With a **profile**, every image can be the same recurring character (identity preserved from reference photos) on a consistent persona.

The pipeline has two outputs: **the image on ImageKit** and **a HiveMQ message** describing the post. The downstream [tiktok-agent](https://github.com/zazin/tiktok-agent) subscribes to the HiveMQ topic to post the content.

## Files

| File | Purpose |
|------|---------|
| `tiktok_pipeline.py` | **Top-level app** — AI idea → image → ImageKit → HiveMQ |
| `idea_generator.py` | Invent a TikTok image idea via Claude (on TokenRouter) |
| `content_generator.py` | Generate a TikTok post's image prompt + caption + description + hashtags (text-only AI call) |
| `profile_loader.py` | Load a `profiles/<name>/` persona + reference images |
| `profiles/<name>/` | A persona (`profile.json`) + reference photos of one person |
| `tiktok_image_generator.py` | Generate 9:16 images via TokenRouter API |
| `imagekit_uploader.py` | Upload generated images to ImageKit CDN |
| `hivemq_publisher.py` | Publish one post message per run to a HiveMQ Cloud topic |
| `env_loader.py` | Zero-dependency `.env` loader used by every CLI |
| `tiktok_output/` | Folder where all generated images are stored |
| `pyproject.toml` / `uv.lock` | uv project definition, console scripts, pinned deps |

## Quick Start

This project uses [uv](https://docs.astral.sh/uv/) as its package manager.

```bash
# 1. Install deps (creates .venv from pyproject.toml + uv.lock)
uv sync

# 2. Set up env — create a .env file (auto-loaded by every command):
#   TOKENROUTER_API_KEY=your_key      # idea + image generation
#   IMAGEKIT_PRIVATE_KEY=your_key     # ImageKit upload
#   IMAGEKIT_PUBLIC_KEY=your_key
#   IMAGEKIT_URL_ENDPOINT=https://ik.imagekit.io/your_id
#   HIVEMQ_HOST=xxxx.s1.eu.hivemq.cloud   # HiveMQ publish
#   HIVEMQ_USERNAME=your_user
#   HIVEMQ_PASSWORD=your_pass
# (or just export them — real env vars take precedence over .env)

# 3. Fully automatic: AI idea → image → ImageKit → HiveMQ
uv run tiktok-pipeline

# 4. Steer the AI idea by theme
uv run tiktok-pipeline --theme "cyberpunk street food at night"

# 6. Bring your own prompt (skip the AI idea step)
uv run tiktok-pipeline --prompt "neon skyline at dusk"

# 7. Generate as a recurring character via a profile (persona + face reference)
uv run tiktok-pipeline --profile kalila --theme "morning skincare routine"
```

### Profiles (recurring characters)

A profile keeps a person consistent across posts. `profiles/<name>/` holds reference
photos plus a `profile.json`:

```json
{
  "name": "Kalila",
  "persona": "who they are, their vibe, niche and tone…",
  "reference_images": ["portrait.jpeg", "full_body.jpeg"],
  "reference_kind": "preserve"
}
```

With `--profile <name>`, the pipeline (1) **preserves the person's identity** by passing the
reference images to the image model, and (2) **steers the AI idea + caption** with the persona,
so every image is the same person, on-brand. Inspect a profile with `uv run tiktok-profile <name>`.

Optional fields — `gender`, `generation`, `age`, `industry`, and a `content_pillars` list — are
folded into the effective persona automatically, so you can keep the structured brand brief in the
same file. Adding a new character is just `mkdir profiles/<name>/`, drop in photos, write a
`profile.json` — no code changes.

### Individual steps

Each stage is also exposed as its own `uv run` command:

```bash
# Generate only
uv run tiktok-generate "a cat wearing red boots" --out cat.png

# Generate + upload to ImageKit
uv run tiktok-generate "neon skyline" --out skyline.png --upload

# Upload an existing image to ImageKit
uv run imagekit-upload cat.png --folder /tiktok

# Publish a single HiveMQ message by hand (testing the publisher)
uv run hivemq-publish --idea "a cat in red boots" --caption "..." --image-url https://ik.imagekit.io/salt/x.png --json

# Just generate an idea
uv run tiktok-idea --theme "cozy coffee shop"

# Just generate a caption + description for a concept (Indonesian by default)
uv run tiktok-content "a jade-green matcha latte on white marble"

# Generate the post copy in English instead
uv run tiktok-content "a jade-green matcha latte on white marble" --language en

# List / inspect profiles
uv run tiktok-profile --list
uv run tiktok-profile kalila
```

You can still run the modules directly (e.g. `uv run python tiktok_pipeline.py ...`) if you prefer.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.10+ (uv provisions this for you)
- An ImageKit account (`IMAGEKIT_PRIVATE_KEY` / `IMAGEKIT_PUBLIC_KEY`)
- A HiveMQ Cloud broker (`HIVEMQ_HOST` / `HIVEMQ_USERNAME` / `HIVEMQ_PASSWORD`; optional `HIVEMQ_PORT`, `HIVEMQ_TOPIC`, `HIVEMQ_CLIENT_ID`) for the post hand-off (`--no-hivemq` to skip). See [docs/hivemq.md](docs/hivemq.md).

Runtime dependencies (`requests`, `pillow`, `paho-mqtt`) are declared in `pyproject.toml` and pinned in `uv.lock` — `uv sync` installs them. The idea generator uses an Anthropic Claude model **served through TokenRouter**, so it reuses `TOKENROUTER_API_KEY` — no separate Anthropic key or SDK needed.

## Pipeline Flow

1. (optional) Theme → AI → image idea  *(skipped if you pass `--prompt`)*
2. Idea → AI → **caption + description** (separate text-only call; `--no-caption` to skip). The
   post copy is written in Indonesian by default; pass `--language en` for English (`--language id|en`).
3. Idea (+ profile reference images, if `--profile`) → TokenRouter image model → 9:16 image in
   `tiktok_output/`, named `tiktok_YYYYMMDD_HHMMSS.<ext>`. The model occasionally returns no image
   (a refusal, common on reference-image edits of real faces); the generator auto-retries
   (`--retries`, default 2) before failing.
4. Image → **ImageKit** → public CDN URL (`--no-imagekit` to skip). Non-fatal: a failure is
   recorded in the result.
5. Idea + caption + description + ImageKit URL → **HiveMQ** message on topic `tiktok/posts`, with
   `Status = pending` (`--no-hivemq` to skip). Non-fatal: a broker failure is recorded in the
   result (the CLI still exits non-zero). See [docs/hivemq.md](docs/hivemq.md).

The post details are published over **HiveMQ**, not in ImageKit metadata. The downstream
[tiktok-agent](https://github.com/zazin/tiktok-agent) subscribes to the topic, posts the content
using the `ImageURL` + `Caption` + `Description`, and marks it done. Delivery is QoS 1 with a
durable subscription on the agent side — see [docs/hivemq.md](docs/hivemq.md).

### HiveMQ message payload

JSON on topic `tiktok/posts` (default; override with `HIVEMQ_TOPIC`):

| Field | Value |
|-------|-------|
| `Idea` | the idea |
| `Caption` | AI caption |
| `Description` | AI description |
| `ImageURL` | ImageKit public URL |
| `ImageKitFileId` | ImageKit file id |
| `ImagePath` | image filename incl. ext |
| `Profile` | profile name (if `--profile`) |
| `Status` | `pending` |
| `CreatedAt` | ISO-8601 UTC timestamp (auto) |

## Skills (for other agents)

Each pipeline stage is also packaged as a standalone [Agent Skill](https://agentskills.io)
under [`skills/`](skills/), so other AI agents can install and run a single capability
with [`npx skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add zazin/tiktok-pipeline/skills/tiktok-image      # one capability
npx skills add zazin/tiktok-pipeline/skills/tiktok-content    # another
```

The `scripts/` bundle inside each skill is **generated** from the root modules (the
single source of truth). After changing a module, regenerate the copies with
`bash skills/sync.sh`. See [`skills/README.md`](skills/README.md) for the full list.

## Repo

[zazin/tiktok-pipeline](https://github.com/zazin/tiktok-pipeline)
