---
name: tiktok-publish
description: Publish a finished image to TikTok by uploading it to ImageKit (public CDN URL), writing one Status=pending Posts record to Airtable, and pushing a real-time HiveMQ trigger; the downstream tiktok-agent reacts to the push (and can fall back to pending rows) and does the actual posting. Use when an agent has an image file ready and wants it queued for TikTok. Requires IMAGEKIT_PRIVATE_KEY, (unless --no-airtable) AIRTABLE_API_KEY/AIRTABLE_BASE_ID/AIRTABLE_TABLE_NAME, and (unless --no-hivemq) HIVEMQ_HOST/HIVEMQ_USERNAME/HIVEMQ_PASSWORD.
---

# TikTok Publish (ImageKit + Airtable + HiveMQ)

Takes a local image, uploads it to ImageKit, writes one `Posts` record to Airtable
(idea, caption, description, the ImageKit URL + fileId, the image filename, profile,
status — `Status=pending` by default), then pushes a real-time HiveMQ message (the
same fields plus the new Airtable record id) to topic `tiktok/posts`. The Airtable
record is the durable source of truth; the HiveMQ push triggers the downstream
tiktok-agent instantly. Pairs with the `tiktok-image` skill (which only generates
the local image).

## Requirements

- `IMAGEKIT_PRIVATE_KEY` — ImageKit upload (Basic-auth username, empty password).
- `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME` — the Airtable
  record (not needed with `--no-airtable`). The `Posts` table must already exist
  (fields: Idea, Caption, Description, ImageURL, ImageKitFileId, ImagePath,
  Profile, Status, CreatedAt).
- `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD` — the HiveMQ Cloud push (not
  needed with `--no-hivemq`; also skipped when there is no Airtable record).
  Optional: `HIVEMQ_PORT` (default 8883), `HIVEMQ_TOPIC` (default `tiktok/posts`),
  `HIVEMQ_CLIENT_ID`. The publish is best-effort — a failure is reported but does
  not fail the run.
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `requests` + `paho-mqtt`.

## Run

```bash
# upload + write a pending Posts record
uv run scripts/tiktok_publish.py ./tiktok_output/x.png --idea "a cat in red boots" --caption "morning vibes"

# upload only, no Airtable record (also skips HiveMQ — it needs the record id)
uv run scripts/tiktok_publish.py ./x.png --no-airtable --folder /tiktok

# upload + Airtable record, but skip the HiveMQ push
uv run scripts/tiktok_publish.py ./x.png --idea "..." --no-hivemq
```

Without `uv`: `pip install requests paho-mqtt` then `python3 scripts/tiktok_publish.py ...`.

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
- `--no-airtable` — upload to ImageKit only; skip the record (and the HiveMQ push).
- `--no-hivemq` — skip the HiveMQ trigger (still uploads + records to Airtable).
- `--json` — print the full result JSON.

## Output & errors

Default output: the public ImageKit URL, the Airtable record id (unless
`--no-airtable`), and the HiveMQ topic when the push succeeds. `ImageURL`,
`ImageKitFileId`, and `ImagePath` are filled from the upload automatically —
`ImagePath` is the **actual name ImageKit stored the file under** (matches
`ImageURL`), so with the default (no `--unique`) it stays the clean
`tiktok_YYYYMMDD_HHMMSS.png` produced by `tiktok-image`. Only non-empty fields are
sent. Exits non-zero if the ImageKit upload or the Airtable write fails; a HiveMQ
publish failure is reported on stderr but does **not** fail the run.
