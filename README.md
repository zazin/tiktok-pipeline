# TikTok Image Pipeline

Generate TikTok-ready 9:16 images with AI, then deliver them to your Android phone (adb) and ImageKit CDN. The whole flow can run fully automatically: an AI invents the image idea, an image model renders it, and it's pushed to both targets.

## Files

| File | Purpose |
|------|---------|
| `tiktok_pipeline.py` | **Top-level app** — AI idea → image → phone + ImageKit |
| `idea_generator.py` | Invent a TikTok image idea via Claude (on TokenRouter) |
| `caption_generator.py` | Generate a TikTok caption + description (text-only AI call) |
| `profile_loader.py` | Load a `profiles/<name>/` persona + reference images |
| `profiles/<name>/` | A persona (`profile.json`) + reference photos of one person |
| `tiktok_image_generator.py` | Generate 9:16 images via TokenRouter API |
| `phone_uploader.py` | Push images to an Android phone over USB (adb) |
| `imagekit_uploader.py` | Upload generated images to ImageKit CDN |
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
# (or just export them — real env vars take precedence over .env)

# 3. Fully automatic: AI idea → image → phone + ImageKit
uv run tiktok-pipeline

# 4. Steer the AI idea by theme
uv run tiktok-pipeline --theme "cyberpunk street food at night"

# 5. Bring your own prompt, ImageKit only (no phone connected)
uv run tiktok-pipeline --prompt "neon skyline at dusk" --no-phone

# 6. Generate as a recurring character via a profile (persona + face reference)
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

### Individual steps

Each stage is also exposed as its own `uv run` command:

```bash
# Generate only
uv run tiktok-generate "a cat wearing red boots" --out cat.png

# Generate + upload to ImageKit
uv run tiktok-generate "neon skyline" --out skyline.png --upload

# Push an image to a connected Android phone (USB debugging on)
uv run phone-upload cat.png --dest /sdcard/Pictures

# Upload an existing image to ImageKit
uv run imagekit-upload cat.png --folder /tiktok

# Just generate an idea
uv run tiktok-idea --theme "cozy coffee shop"
```

You can still run the modules directly (e.g. `uv run python tiktok_pipeline.py ...`) if you prefer.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.10+ (uv provisions this for you)
- `adb` (`brew install android-platform-tools`) — only for phone delivery
- Android phone with **USB debugging** enabled — only for phone delivery

Runtime dependencies (`requests`, `pillow`) are declared in `pyproject.toml` and pinned in `uv.lock` — `uv sync` installs them. The idea generator uses an Anthropic Claude model **served through TokenRouter**, so it reuses `TOKENROUTER_API_KEY` — no separate Anthropic key or SDK needed.

## Pipeline Flow

1. (optional) Theme → AI → image idea  *(skipped if you pass `--prompt`)*
2. Idea → AI → **caption + description** (separate text-only call; `--no-caption` to skip)
3. Idea → TokenRouter image model → 9:16 image in `tiktok_output/`, named `tiktok_YYYYMMDD_HHMMSS.<ext>`
4. Image → **phone** (adb push) **and** → **ImageKit** (CDN URL + caption/description as
   custom metadata), independently — a failure in one delivery target does not abort the other

The caption/description travel with the image as ImageKit **custom metadata** (`caption`,
`description` fields), so the downstream [tiktok-agent](https://github.com/zazin/tiktok-agent)
can read them back and post the AI caption. Those two custom-metadata fields must exist in the
ImageKit account (create once via the dashboard or the `customMetadataFields` API).

## Repo

[zazin/tiktok-pipeline](https://github.com/zazin/tiktok-pipeline)
