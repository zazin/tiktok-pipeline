---
name: airtable-log
description: Write one post record (idea, caption, description, image URL, status, ...) to an Airtable table via the REST API. Use when an agent needs to persist a generated post so a downstream consumer can pick it up. Requires AIRTABLE_API_KEY, AIRTABLE_BASE_ID, and AIRTABLE_TABLE_NAME.
---

# Airtable Logger

Creates a single record in the configured Airtable table. Auto-stamps a `CreatedAt`
ISO-8601 UTC timestamp if not supplied, and sends `typecast: true` so string values
coerce into the correct field types. Expects the table created by the
`airtable-migrate` skill (fields: Idea, Caption, Description, ImageURL,
ImageKitFileId, ImagePath, Profile, Status, CreatedAt).

## Requirements

- `AIRTABLE_API_KEY` — Bearer personal access token with `data.records:write`.
- `AIRTABLE_BASE_ID` — base id (`app...`).
- `AIRTABLE_TABLE_NAME` — target table (name or `tbl...` id).
- Read from the real environment or a `.env` in the cwd (or next to the script).
- `uv` recommended — the inline PEP 723 header auto-installs `requests`.

## Run

```bash
uv run scripts/airtable_logger.py \
  --idea "a cat in red boots" \
  --caption "..." --description "..." \
  --image-url https://ik.imagekit.io/salt/x.png \
  --status pending
```

Without `uv`: `pip install requests` then `python3 scripts/airtable_logger.py ...`.

## Flags

- `--idea TEXT` — idea (primary field).
- `--caption TEXT`, `--description TEXT` — post copy.
- `--image-url URL` — public image URL.
- `--file-id ID` — ImageKit file id.
- `--image-path NAME` — image filename incl. extension.
- `--profile NAME` — profile name used for the post.
- `--status VALUE` — record status (default `pending`).
- `--json` — print the full created-record JSON.

## Output & errors

Returns the created record (with `id` and `createdTime`). This step is intended to be
fatal in a pipeline: it raises / exits non-zero on missing credentials, network error,
or a non-200 API response.
