---
name: tiktok-publish
description: Publish a finished image to TikTok by uploading it to ImageKit (public CDN URL) and writing one Status=pending Posts record to Airtable; the downstream tiktok-agent reads pending rows and does the actual posting. Use when an agent has an image file ready and wants it queued for TikTok. Requires IMAGEKIT_PRIVATE_KEY and (unless --no-airtable) AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME.
---

# TikTok Publish (ImageKit + Airtable)

Takes a local image, uploads it to ImageKit, then writes one `Posts` record to
Airtable (idea, caption, description, the ImageKit URL + fileId, the image
filename, profile, status — `Status=pending` by default). That record is what gets
the post onto TikTok: the downstream tiktok-agent reads `pending` rows and posts
them. Pairs with the `tiktok-image` skill (which only generates the local image).

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
uv run scripts/tiktok_publish.py ./tiktok_output/x.png --idea "a cat in red boots" --caption "morning vibes"

# upload only, no Airtable record
uv run scripts/tiktok_publish.py ./x.png --no-airtable --folder /tiktok
```

Without `uv`: `pip install requests` then `python3 scripts/tiktok_publish.py ...`.

## Flags

- `image` (positional) — local image file to upload.
- `--folder PATH` — ImageKit destination folder (default `/tiktok`).
- `--idea TEXT` — Airtable `Idea` field (primary).
- `--caption TEXT`, `--description TEXT` — Airtable `Caption` / `Description`.
- `--profile NAME` — Airtable `Profile` field.
- `--status VALUE` — Airtable `Status` field (default `pending`).
- `--unique` — let ImageKit append a random suffix to the file name. Off by
  default so the file keeps its exact name (e.g. `tiktok_YYYYMMDD_HHMMSS.png` from
  the `tiktok-image` skill, which is already unique). Turning this on can produce
  names like `name_-Ab12.png`.
- `--no-airtable` — upload to ImageKit only; skip the record.
- `--json` — print the full result JSON.

## Output & errors

Default output: the public ImageKit URL, plus the Airtable record id (unless
`--no-airtable`). `ImageURL`, `ImageKitFileId`, and `ImagePath` are filled from the
upload automatically — `ImagePath` is the **actual name ImageKit stored the file
under** (matches `ImageURL`), so with the default (no `--unique`) it stays the clean
`tiktok_YYYYMMDD_HHMMSS.png` produced by `tiktok-image`. Only non-empty fields are
sent. Exits non-zero if the ImageKit upload or the Airtable write fails.
