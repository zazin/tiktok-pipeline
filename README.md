# TikTok Image Pipeline

Generate TikTok-ready 9:16 images with AI, then deliver them to your Android phone (adb) and ImageKit CDN. The whole flow can run fully automatically: an AI invents the image idea, an image model renders it, and it's pushed to both targets.

## Files

| File | Purpose |
|------|---------|
| `tiktok_pipeline.py` | **Top-level app** — AI idea → image → phone + ImageKit |
| `idea_generator.py` | Invent a TikTok image idea via Claude (on TokenRouter) |
| `tiktok_image_generator.py` | Generate 9:16 images via TokenRouter API |
| `phone_uploader.py` | Push images to an Android phone over USB (adb) |
| `imagekit_uploader.py` | Upload generated images to ImageKit CDN |
| `tiktok_output/` | Folder where all generated images are stored |

## Quick Start

```bash
# 1. Install deps + set up env
pip install requests pillow
export TOKENROUTER_API_KEY="your_key"     # idea + image generation
export IMAGEKIT_PRIVATE_KEY="your_key"    # ImageKit upload
export IMAGEKIT_PUBLIC_KEY="your_key"
export IMAGEKIT_URL_ENDPOINT="https://ik.imagekit.io/your_id"

# 2. Fully automatic: AI idea → image → phone + ImageKit
python tiktok_pipeline.py

# 3. Steer the AI idea by theme
python tiktok_pipeline.py --theme "cyberpunk street food at night"

# 4. Bring your own prompt, ImageKit only (no phone connected)
python tiktok_pipeline.py --prompt "neon skyline at dusk" --no-phone
```

### Individual steps

```bash
# Generate only
python tiktok_image_generator.py "a cat wearing red boots" --out cat.png

# Generate + upload to ImageKit
python tiktok_image_generator.py "neon skyline" --out skyline.png --upload

# Push an image to a connected Android phone (USB debugging on)
python phone_uploader.py cat.png --dest /sdcard/Pictures

# Upload an existing image to ImageKit
python imagekit_uploader.py cat.png --folder /tiktok

# Just generate an idea
python idea_generator.py --theme "cozy coffee shop"
```

## Requirements

- Python 3.10+
- `requests`, `pillow`
- `adb` (`brew install android-platform-tools`) — only for phone delivery
- Android phone with **USB debugging** enabled — only for phone delivery

The idea generator uses an Anthropic Claude model **served through TokenRouter**, so it reuses `TOKENROUTER_API_KEY` — no separate Anthropic key or SDK needed.

## Pipeline Flow

1. (optional) Theme → AI → image idea  *(skipped if you pass `--prompt`)*
2. Idea → TokenRouter image model → 9:16 PNG in `tiktok_output/`
3. PNG → **phone** (adb push) **and** → **ImageKit** (CDN URL), independently
   — a failure in one delivery target does not abort the other

## Repo

[zazin/tiktok-pipeline](https://github.com/zazin/tiktok-pipeline)
