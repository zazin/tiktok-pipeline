---
name: airtable-migrate
description: Idempotently create (or additively extend) the Airtable Posts table schema via the Airtable Meta API, so the airtable-log skill has fields to write into. Run once before the first log. Requires AIRTABLE_API_KEY with schema scopes, AIRTABLE_BASE_ID, and AIRTABLE_TABLE_NAME.
---

# Airtable Schema Migrate

Ensures the configured table exists with all required fields. **Additive only** — it
can create the table and add missing fields, but cannot delete, rename, or retype an
existing field (do those by hand in the Airtable UI). Safe to re-run.

Fields it ensures: `Idea` (primary, singleLineText), `Caption` (multilineText),
`Description` (multilineText), `ImageURL` (url), `ImageKitFileId` (singleLineText),
`ImagePath` (singleLineText), `Profile` (singleLineText), `Status` (singleSelect:
pending / posted / failed), `CreatedAt` (dateTime, ISO, 24-hour, UTC).

## Requirements

- `AIRTABLE_API_KEY` — Bearer PAT with `schema.bases:write` + `schema.bases:read`.
- `AIRTABLE_BASE_ID` — base id (`app...`).
- `AIRTABLE_TABLE_NAME` — target table name.
- Read from the real environment or a `.env` in the cwd (or next to the script).
- `uv` recommended — the inline PEP 723 header auto-installs `requests`.

## Run

```bash
uv run scripts/airtable_migrate.py
```

Takes no flags; reads everything from the environment. Without `uv`:
`pip install requests` then `python3 scripts/airtable_migrate.py`.

## Output & errors

Prints a summary: table id, whether the table was created, and which fields were
added / already existed / mismatched. Exits non-zero on network or API error.
