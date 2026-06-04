# TikTok Image Pipeline

Generate TikTok-ready 9:16 images using TokenRouter image generation + ImageKit CDN upload.

## Files

| File | Purpose |
|------|---------|
| `tiktok_image_generator.py` | Generate 9:16 images via TokenRouter API |
| `imagekit_uploader.py` | Upload generated images to ImageKit CDN |
| `TIKTOK_SETUP.md` | Environment & API setup guide |
| `TIKTOK_WORKFLOW_COMPLETE.md` | Full workflow documentation |

## Quick Start

```bash
# 1. Set up env
export TOKENROUTER_API_KEY="your_key"
export IMAGEKIT_PRIVATE_KEY="your_key"
export IMAGEKIT_PUBLIC_KEY="your_key"
export IMAGEKIT_URL_ENDPOINT="https://ik.imagekit.io/your_id"

# 2. Generate image
python tiktok_image_generator.py "a cat smiling wearing red boots" --out cat.png

# 3. Generate + auto-upload to ImageKit
python tiktok_image_generator.py "neon skyline" --out skyline.png --upload

# 4. Or upload existing image
python imagekit_uploader.py cat.png --folder /tiktok
```

## Requirements

- Python 3.10+
- `requests`
- `python-dotenv` (optional, for `.env` loading)

## Pipeline Flow

1. Prompt → TokenRouter image model → 9:16 PNG
2. PNG → ImageKit uploader → CDN URL
3. URL → post to TikTok / social scheduler

## Repo

[zazin/tiktok-pipeline](https://github.com/zazin/tiktok-pipeline)
