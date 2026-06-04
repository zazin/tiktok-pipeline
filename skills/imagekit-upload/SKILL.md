---
name: imagekit-upload
description: Upload one or more local images to ImageKit and get back public CDN URLs. Use when an agent has image files on disk and needs hosted, shareable URLs. Requires IMAGEKIT_PRIVATE_KEY.
---

# ImageKit Uploader

Uploads local image file(s) to ImageKit as public files and returns their public
CDN URLs (and full metadata with `--json`). Batch uploads report per-file status.

## Requirements

- `IMAGEKIT_PRIVATE_KEY` — used as the Basic-auth username (empty password). Read
  from the real environment or a `.env` in the cwd (or next to the script).
- `uv` recommended — the inline PEP 723 header auto-installs `requests`.

## Run

```bash
uv run scripts/imagekit_uploader.py img.png --folder /tiktok
uv run scripts/imagekit_uploader.py *.jpg --folder /gallery --json
```

Without `uv`: `pip install requests` then `python3 scripts/imagekit_uploader.py ...`.

## Flags

- `paths` (positional, one or more) — image file path(s) to upload.
- `--folder PATH` — destination folder (default `/tiktok`).
- `--name NAME` — override the file name (single-file only).
- `--tags a,b,c` — comma-separated tags.
- `--no-unique` — disable the unique-name suffix (overwrite by name).
- `--json` — print the full JSON response instead of just the URL(s).

## Output & errors

Default output: the public URL(s), one per line. `--json` returns the full ImageKit
record(s) (`fileId`, `name`, `url`, `filePath`, `thumbnailUrl`, `width`, `height`,
`size`, ...). Exits non-zero on missing credentials, network error, or a non-200 API
response.
