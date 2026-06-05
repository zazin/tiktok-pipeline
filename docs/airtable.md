# Airtable schema — the `Posts` table

This document describes the Airtable table that the TikTok pipeline writes to. It is the
reference for any **downstream app** (the separate `tiktok-agent`) that reads these records
to post content to TikTok.

## Overview

The pipeline's single durable hand-off is one Airtable table (default name **`Posts`**).
For every generated post, the pipeline writes **one record** with `Status = "pending"`
containing the caption, description, and the public image URL. The downstream tiktok-agent
treats this table as a **queue**: it reads `pending` rows, posts them to TikTok, then flips
`Status` to `posted` (or `failed`).

This Airtable record replaced an older hand-off that used ImageKit custom metadata; the
pipeline no longer writes any ImageKit metadata — Airtable is the source of truth.

## Connection / access

The table is reached through the standard Airtable REST API.

| Variable | Purpose |
|----------|---------|
| `AIRTABLE_API_KEY` | Personal access token (PAT). Needs scope `data.records:write` to write records; `airtable-migrate` additionally needs `schema.bases:write` (+ `schema.bases:read`). A reader only needs `data.records:read`. |
| `AIRTABLE_BASE_ID` | The base id, starts with `app…`. |
| `AIRTABLE_TABLE_NAME` | The table name (default `Posts`) — may also be a table id (`tbl…`). |

- **Base URL:** `https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}`
- **Auth:** `Authorization: Bearer {AIRTABLE_API_KEY}`
- The pipeline writes with `typecast: true`, so plain string values are coerced into the
  correct field types (e.g. the `Status` single-select, the `CreatedAt` dateTime).

## Fields

Listed in schema order. The **first field (`Idea`) is the table's primary field.** Every
field is written as a string by the pipeline and coerced via `typecast`.

| Field | Airtable type | Written by | Purpose / example |
|-------|---------------|------------|-------------------|
| `Idea` | `singleLineText` (primary) | pipeline | The one-line image idea / topic. e.g. `a cat smiling wearing red boots` |
| `Caption` | `multilineText` | pipeline | The post caption. May contain emojis. **No hashtags.** Capped at 90 chars. |
| `Description` | `multilineText` | pipeline | One or two plain sentences of context. No hashtags. |
| `ImageURL` | `url` | pipeline | Public ImageKit CDN URL of the 9:16 image. This is the image to attach when posting. e.g. `https://ik.imagekit.io/salt/tiktok/tiktok_20260604_230055.jpeg` |
| `ImageKitFileId` | `singleLineText` | pipeline | ImageKit `fileId` for the uploaded image — use it for later lookup/delete on ImageKit. |
| `ImagePath` | `singleLineText` | pipeline | The stored image filename incl. extension, e.g. `tiktok_20260604_230055.jpeg`. (Matches the file name in `ImageURL`.) |
| `Profile` | `singleLineText` | pipeline | The persona/profile name used to generate the post (e.g. `kalila`). Empty string when no profile was used. |
| `Status` | `singleSelect` | pipeline writes `pending`; downstream agent updates | Workflow state — see below. |
| `CreatedAt` | `dateTime` (ISO format, 24-hour, UTC) | pipeline | ISO-8601 UTC timestamp stamped when the record is created (e.g. `2026-06-04T23:00:55+00:00`). The logger sets it automatically if the caller omits it. |

Notes:
- **Hashtags are intentionally NOT stored.** The content step generates a hashtag list but
  the pipeline does not log it; captions/descriptions deliberately contain no hashtags. If a
  consumer needs hashtags it must generate or maintain them on its own.
- `ImageURL` / `ImageKitFileId` may be empty strings if the ImageKit upload failed (the
  upload step is non-fatal); the record is still written so the failure is visible.

## Status workflow

`Status` is a single-select with exactly three choices:

| Value | Meaning |
|-------|---------|
| `pending` | Freshly written by the pipeline. Ready to be posted. **This is the value a consumer should query for.** |
| `posted` | The downstream agent successfully posted it to TikTok. |
| `failed` | The downstream agent tried and failed to post it. |

Lifecycle: the pipeline always writes `pending`. The tiktok-agent picks up `pending` rows,
attempts to post, and flips the row to `posted` or `failed`.

## Reading & updating records (consumer guidance)

**Fetch the work queue** — pending rows only:

```bash
curl -s "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Posts" \
  -H "Authorization: Bearer $AIRTABLE_API_KEY" \
  --data-urlencode 'filterByFormula={Status}="pending"' \
  --data-urlencode 'sort[0][field]=CreatedAt' \
  --data-urlencode 'sort[0][direction]=asc' \
  -G
```

Sample record shape returned by Airtable:

```json
{
  "records": [
    {
      "id": "recXXXXXXXXXXXXXX",
      "createdTime": "2026-06-04T23:00:55.000Z",
      "fields": {
        "Idea": "a cat smiling wearing red boots",
        "Caption": "When the boots match the vibe 🐾🔥",
        "Description": "A cheerful cat showing off its bright red boots.",
        "ImageURL": "https://ik.imagekit.io/salt/tiktok/tiktok_20260604_230055.jpeg",
        "ImageKitFileId": "6650f1a2b3c4d5e6f7a8b9c0",
        "ImagePath": "tiktok_20260604_230055.jpeg",
        "Profile": "kalila",
        "Status": "pending",
        "CreatedAt": "2026-06-04T23:00:55+00:00"
      }
    }
  ]
}
```

**Mark a record done** after posting — `PATCH` the record id:

```bash
curl -s -X PATCH "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Posts/recXXXXXXXXXXXXXX" \
  -H "Authorization: Bearer $AIRTABLE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"Status": "posted"}}'
```

## Schema management

The table and its fields are created/extended by:

```bash
uv run airtable-migrate
```

This uses the Airtable **Meta API** and is **additive only** — it can create the table and
add missing fields, but it **cannot delete, rename, or retype** a field. To remove or change
the type of a field, edit it by hand in the Airtable UI. The authoritative field list lives
in `airtable_migrate.py` (`DESIRED_FIELDS`).
