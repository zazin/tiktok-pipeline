# TikTok Image Pipeline

Generate TikTok-ready 9:16 images with AI, upload them to ImageKit CDN, and record each post in Airtable. The whole flow can run fully automatically: an AI invents the image idea, writes a matching caption, an image model renders it, the image is uploaded to ImageKit, and a row describing the post is written to Airtable. With a **profile**, every image can be the same recurring character (identity preserved from reference photos) on a consistent persona.

The pipeline has exactly two outputs: **the image on ImageKit** and **a post record in Airtable**. The downstream [tiktok-agent](https://github.com/zazin/tiktok-agent) reads the Airtable row to post the content.

## Files

| File | Purpose |
|------|---------|
| `tiktok_pipeline.py` | **Top-level app** — AI idea → image → ImageKit → Airtable |
| `idea_generator.py` | Invent a TikTok image idea via Claude (on TokenRouter) |
| `caption_generator.py` | Generate a TikTok caption + description (text-only AI call) |
| `profile_loader.py` | Load a `profiles/<name>/` persona + reference images |
| `profiles/<name>/` | A persona (`profile.json`) + reference photos of one person |
| `tiktok_image_generator.py` | Generate 9:16 images via TokenRouter API |
| `imagekit_uploader.py` | Upload generated images to ImageKit CDN |
| `airtable_logger.py` | Write one post record per run to the Airtable `Posts` table |
| `airtable_migrate.py` | One-time/idempotent additive setup of the `Posts` table schema |
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
#   AIRTABLE_API_KEY=your_token       # Airtable record
#   AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
#   AIRTABLE_TABLE_NAME=Posts
# (or just export them — real env vars take precedence over .env)

# 3. One-time: create the Airtable Posts table (idempotent, additive)
uv run airtable-migrate

# 4. Fully automatic: AI idea → image → ImageKit → Airtable
uv run tiktok-pipeline

# 5. Steer the AI idea by theme
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

# Write a single Airtable record by hand (testing the logger)
uv run airtable-log --idea "a cat in red boots" --caption "..." --image-url https://ik.imagekit.io/salt/x.png

# Set up / extend the Airtable Posts table schema (additive, idempotent)
uv run airtable-migrate

# Just generate an idea
uv run tiktok-idea --theme "cozy coffee shop"

# Just generate a caption + description for a concept
uv run tiktok-caption "a jade-green matcha latte on white marble"

# List / inspect profiles
uv run tiktok-profile --list
uv run tiktok-profile kalila
```

You can still run the modules directly (e.g. `uv run python tiktok_pipeline.py ...`) if you prefer.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.10+ (uv provisions this for you)
- An ImageKit account (`IMAGEKIT_PRIVATE_KEY` / `IMAGEKIT_PUBLIC_KEY`)
- An Airtable base + personal access token (`AIRTABLE_API_KEY` / `AIRTABLE_BASE_ID` / `AIRTABLE_TABLE_NAME`). The token needs `data.records:write`, plus `schema.bases:write` to run `airtable-migrate`.

Runtime dependencies (`requests`, `pillow`) are declared in `pyproject.toml` and pinned in `uv.lock` — `uv sync` installs them. The idea generator uses an Anthropic Claude model **served through TokenRouter**, so it reuses `TOKENROUTER_API_KEY` — no separate Anthropic key or SDK needed.

## Pipeline Flow

1. (optional) Theme → AI → image idea  *(skipped if you pass `--prompt`)*
2. Idea → AI → **caption + description** (separate text-only call; `--no-caption` to skip)
3. Idea (+ profile reference images, if `--profile`) → TokenRouter image model → 9:16 image in
   `tiktok_output/`, named `tiktok_YYYYMMDD_HHMMSS.<ext>`. The model occasionally returns no image
   (a refusal, common on reference-image edits of real faces); the generator auto-retries
   (`--retries`, default 2) before failing.
4. Image → **ImageKit** → public CDN URL (`--no-imagekit` to skip). Non-fatal: a failure is
   recorded in the result.
5. Idea + caption + description + ImageKit URL → **Airtable** record in the `Posts` table, with
   `Status = pending` (`--no-airtable` to skip). **Fatal** — without the row there is nothing for
   the agent to post.

The post details live in **Airtable**, not in ImageKit metadata. The downstream
[tiktok-agent](https://github.com/zazin/tiktok-agent) reads `Status = "pending"` rows from the
`Posts` table, posts them using the `ImageURL` + `Caption` + `Description`, and flips `Status`
to `posted` (or `failed`). Create the table once with `uv run airtable-migrate` — it is additive
only (the Airtable Meta API cannot delete, rename, or retype a field; do those in the Airtable UI).

### Airtable `Posts` schema

| Field | Type | Written by the pipeline |
|-------|------|--------------------------|
| `Idea` | Single line text (primary) | the idea |
| `Caption` | Long text | AI caption |
| `Description` | Long text | AI description |
| `ImageURL` | URL | ImageKit public URL |
| `ImageKitFileId` | Single line text | ImageKit file id |
| `ImagePath` | Single line text | image filename incl. ext |
| `Profile` | Single line text | profile name (if `--profile`) |
| `Status` | Single select (`pending` / `posted` / `failed`) | `pending` |
| `CreatedAt` | Created time | auto (Airtable) |

## Repo

[zazin/tiktok-pipeline](https://github.com/zazin/tiktok-pipeline)
