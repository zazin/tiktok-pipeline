---
name: tiktok-upload
description: Upload a local image to ImageKit (public CDN URL) and write one Posts record to Airtable in a single step — the publish/log step after generating an image. Use when an agent has an image file ready and needs it hosted and recorded for the downstream poster. Requires IMAGEKIT_PRIVATE_KEY and (unless --no-airtable) AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME.
---

# TikTok Upload (ImageKit + Airtable)

Takes a local image, uploads it to ImageKit, then writes one `Posts` record to
Airtable (idea, caption, description, the ImageKit URL + fileId, the image
filename, profile, status). This is the publish/log step that pairs with the
`tiktok-image` skill (which only generates the image now).

## Requirements

- `IMAGEKIT_PRIVATE_KEY` — ImageKit upload (Basic-auth username, empty password).
- `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME` — the Airtable
  record (not needed with `--no-airtable`). The `Posts` table must already exist
  (fields: Idea, Caption, Description, ImageURL, ImageKitFileId, ImagePath,
  Profile, Status, CreatedAt).
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `requests`.

## Run

```bash
# upload + write a pending Posts record
uv run scripts/tiktok_upload.py ./tiktok_output/x.png --idea "a cat in red boots" --caption "morning vibes"

# upload only, no Airtable record
uv run scripts/tiktok_upload.py ./x.png --no-airtable --folder /tiktok
```

Without `uv`: `pip install requests` then `python3 scripts/tiktok_upload.py ...`.

## Flags

- `image` (positional) — local image file to upload.
- `--folder PATH` — ImageKit destination folder (default `/tiktok`).
- `--idea TEXT` — Airtable `Idea` field (primary).
- `--caption TEXT`, `--description TEXT` — Airtable `Caption` / `Description`.
- `--profile NAME` — Airtable `Profile` field.
- `--status VALUE` — Airtable `Status` field (default `pending`).
- `--no-airtable` — upload to ImageKit only; skip the record.
- `--json` — print the full result JSON.

## Output & errors

Default output: the public ImageKit URL, plus the Airtable record id (unless
`--no-airtable`). `ImageURL`, `ImageKitFileId`, and `ImagePath` are filled from the
upload automatically; only non-empty fields are sent. Exits non-zero if the ImageKit
upload or the Airtable write fails.
