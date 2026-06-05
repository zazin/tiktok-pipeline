#!/usr/bin/env python3
"""
Airtable schema migration — one-time / idempotent setup for the Posts table.

Creates the configured table (and any missing fields) in the configured base via
Airtable's Meta API, so airtable_logger.create_record() has somewhere to write.

This is ADDITIVE ONLY. The Airtable Meta API cannot:
  - delete fields or tables,
  - rename a field,
  - change a field's type.
So this script only creates the table if absent and adds any missing fields. To
remove or retype a field, edit it by hand in the Airtable UI.

Credentials / target are read from environment variables:
  - AIRTABLE_API_KEY    — personal access token. For schema changes it needs the
                          scope `schema.bases:write` (plus `schema.bases:read`).
  - AIRTABLE_BASE_ID    — base id ("app..."). Optional; defaults to the project base.
  - AIRTABLE_TABLE_NAME — table name to create/extend. Optional; defaults to "Posts".

Usage (CLI):
    python airtable_migrate.py            # create/extend the table, print a summary
"""

from __future__ import annotations

import sys

import requests

from airtable_logger import (
    AIRTABLE_API_URL,
    AirtableError,
    _get_api_key,
    _get_base_id,
    _get_table_name,
)


# The Status workflow values, as a single-select enum. The pipeline writes
# "pending"; the downstream tiktok-agent flips it to "posted" (or "failed").
STATUS_CHOICES = ["pending", "posted", "failed"]

# Ordered: the FIRST field becomes the table's primary field, which must be a
# single-line / text-like type (long text / url cannot be primary).
DESIRED_FIELDS = [
    {"name": "Idea", "type": "singleLineText"},
    {"name": "Caption", "type": "multilineText"},
    {"name": "Description", "type": "multilineText"},
    {"name": "ImageURL", "type": "url"},
    {"name": "ImageKitFileId", "type": "singleLineText"},
    {"name": "ImagePath", "type": "singleLineText"},
    {"name": "Profile", "type": "singleLineText"},
    {
        "name": "Status",
        "type": "singleSelect",
        "options": {"choices": [{"name": c} for c in STATUS_CHOICES]},
    },
    # Written by the pipeline as an ISO-8601 UTC timestamp when the record is
    # created. (Airtable's Meta API can't create a true read-only createdTime
    # field, so this is a normal dateTime the logger stamps.)
    {
        "name": "CreatedAt",
        "type": "dateTime",
        "options": {
            "dateFormat": {"name": "iso"},
            "timeFormat": {"name": "24hour"},
            "timeZone": "utc",
        },
    },
]


def _meta_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, headers: dict, *, json_body: dict | None = None,
             timeout: int = 30) -> dict:
    try:
        resp = requests.request(method, url, headers=headers, json=json_body,
                                 timeout=timeout)
    except requests.RequestException as e:
        raise AirtableError(f"Network error calling Meta API: {e}") from e

    if resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text)
            if isinstance(err, dict):
                err = err.get("message", err)
        except ValueError:
            err = resp.text
        raise AirtableError(f"Meta API {method} failed (HTTP {resp.status_code}): {err}")

    return resp.json()


def migrate() -> dict:
    """
    Ensure the configured table exists with all DESIRED_FIELDS.

    Returns a summary dict: {"table_id", "created_table": bool, "added_fields": [...],
    "existing_fields": [...]}.
    """
    api_key = _get_api_key()
    base = _get_base_id()
    table = _get_table_name()
    headers = _meta_headers(api_key)

    tables_url = f"{AIRTABLE_API_URL}/meta/bases/{base}/tables"
    listing = _request("GET", tables_url, headers)
    tables = listing.get("tables", [])

    match = next(
        (t for t in tables if t.get("name") == table or t.get("id") == table),
        None,
    )

    # --- Create the table from scratch ----------------------------------
    if match is None:
        created = _request(
            "POST", tables_url, headers,
            json_body={"name": table, "fields": DESIRED_FIELDS},
        )
        return {
            "table_id": created["id"],
            "created_table": True,
            "added_fields": [f["name"] for f in DESIRED_FIELDS],
            "existing_fields": [],
            "mismatched_fields": [],
        }

    # --- Table exists: additively add any missing fields ----------------
    table_id = match["id"]
    existing = {f["name"]: f for f in match.get("fields", [])}
    fields_url = f"{tables_url}/{table_id}/fields"

    added: list[str] = []
    mismatched: list[dict] = []
    for spec in DESIRED_FIELDS:
        cur = existing.get(spec["name"])
        if cur is None:
            _request("POST", fields_url, headers, json_body=spec)
            added.append(spec["name"])
            continue
        # Field exists. The Meta API cannot change a field's type, so flag any
        # mismatch for the user to fix by hand (delete + re-run, in the UI).
        if cur.get("type") != spec["type"]:
            mismatched.append(
                {"name": spec["name"], "have": cur.get("type"), "want": spec["type"]}
            )

    return {
        "table_id": table_id,
        "created_table": False,
        "added_fields": added,
        "existing_fields": sorted(existing),
        "mismatched_fields": mismatched,
    }


def _cli() -> int:
    from env_loader import load_env
    load_env()

    try:
        summary = migrate()
    except AirtableError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    table = _get_table_name()
    if summary["created_table"]:
        print(f"Created table '{table}' ({summary['table_id']}) with fields:")
        for name in summary["added_fields"]:
            print(f"  + {name}")
    else:
        print(f"Table '{table}' ({summary['table_id']}) already exists.")
        if summary["added_fields"]:
            print("Added missing fields:")
            for name in summary["added_fields"]:
                print(f"  + {name}")
        elif not summary.get("mismatched_fields"):
            print("All desired fields already present — nothing to do.")

    mismatched = summary.get("mismatched_fields") or []
    if mismatched:
        print(
            "\nType mismatches (the Airtable API cannot retype a field — delete it "
            "in the Airtable UI, then re-run this migration):",
            file=sys.stderr,
        )
        for m in mismatched:
            print(f"  ! {m['name']}: have '{m['have']}', want '{m['want']}'",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
