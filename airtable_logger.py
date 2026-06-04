#!/usr/bin/env python3
"""
Airtable logger module.

Writes one record per generated TikTok post into an Airtable table. This is the
hand-off to the downstream tiktok-agent (separate repo): it reads back the
caption / description / image URL from Airtable to post the content. (It replaces
the old ImageKit custom-metadata hand-off.)

Credentials / target are read from environment variables:
  - AIRTABLE_API_KEY    — personal access token (needs data.records:write)
  - AIRTABLE_BASE_ID    — base id, starts with "app..."
  - AIRTABLE_TABLE_NAME — table name (e.g. "Posts") or table id ("tbl...")

Create the table/fields once with `airtable_migrate.py` before using this.

Usage (CLI):
    python airtable_logger.py --idea "a cat in red boots" --caption "..." \
        --image-url https://ik.imagekit.io/salt/x.png --status pending

Usage (as a module):
    from airtable_logger import create_record

    rec = create_record({
        "Idea": "...", "Caption": "...", "ImageURL": "...", "Status": "pending",
    })
    print(rec["id"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests


AIRTABLE_API_URL = "https://api.airtable.com/v0"


class AirtableError(Exception):
    """Raised when an Airtable API call fails."""


def _get_api_key() -> str:
    key = os.getenv("AIRTABLE_API_KEY")
    if not key:
        raise AirtableError(
            "AIRTABLE_API_KEY env var is not set. "
            "Export it (or add it to .env) before running."
        )
    return key


def _get_base_id(base_id: Optional[str] = None) -> str:
    base = base_id or os.getenv("AIRTABLE_BASE_ID")
    if not base:
        raise AirtableError(
            "AIRTABLE_BASE_ID env var is not set (expected an 'app...' id)."
        )
    return base


def _get_table_name(table_name: Optional[str] = None) -> str:
    table = table_name or os.getenv("AIRTABLE_TABLE_NAME")
    if not table:
        raise AirtableError(
            "AIRTABLE_TABLE_NAME env var is not set (table name or 'tbl...' id)."
        )
    return table


def _auth_header(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def create_record(
    fields: dict,
    *,
    base_id: Optional[str] = None,
    table_name: Optional[str] = None,
    timeout: int = 30,
) -> dict:
    """
    Create a single record in the configured Airtable table.

    Args:
        fields: Mapping of Airtable field name -> value. Fields must already
            exist in the table (create them once with airtable_migrate.py). A
            "CreatedAt" ISO-8601 UTC timestamp is added automatically unless the
            caller supplies one.
        base_id: Override AIRTABLE_BASE_ID.
        table_name: Override AIRTABLE_TABLE_NAME.
        timeout: Request timeout in seconds.

    Returns:
        The created record JSON, including its "id" and "createdTime".

    Raises:
        AirtableError: On missing creds, network error, or non-200 API response.
    """
    api_key = _get_api_key()
    base = _get_base_id(base_id)
    table = _get_table_name(table_name)

    # Stamp the creation time unless the caller already set one. ISO-8601 UTC.
    fields = dict(fields)
    fields.setdefault("CreatedAt", datetime.now(timezone.utc).isoformat())

    url = f"{AIRTABLE_API_URL}/{base}/{quote(table, safe='')}"
    # typecast lets Airtable coerce strings into the right field types.
    payload = {"fields": fields, "typecast": True}

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={**_auth_header(api_key), "Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise AirtableError(f"Network error creating Airtable record: {e}") from e

    if resp.status_code != 200:
        # Airtable returns {"error": {"type":..., "message":...}}; fall back to text.
        try:
            err = resp.json().get("error", resp.text)
            if isinstance(err, dict):
                err = err.get("message", err)
        except ValueError:
            err = resp.text
        raise AirtableError(f"Create record failed (HTTP {resp.status_code}): {err}")

    return resp.json()


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Create one record in the configured Airtable table."
    )
    parser.add_argument("--idea", default=None, help="Idea (primary field)")
    parser.add_argument("--caption", default=None, help="Caption text")
    parser.add_argument("--description", default=None, help="Description text")
    parser.add_argument("--image-url", default=None, help="Public ImageKit URL")
    parser.add_argument("--file-id", default=None, help="ImageKit file id")
    parser.add_argument("--image-path", default=None, help="Image filename incl. ext (e.g. tiktok_20260604_230055.jpeg)")
    parser.add_argument("--profile", default=None, help="Profile name")
    parser.add_argument("--status", default="pending", help="Status (default: pending)")
    parser.add_argument("--json", action="store_true", help="Print the full record JSON")
    args = parser.parse_args()

    # Only send fields the user actually provided (besides Status, which defaults).
    field_map = {
        "Idea": args.idea,
        "Caption": args.caption,
        "Description": args.description,
        "ImageURL": args.image_url,
        "ImageKitFileId": args.file_id,
        "ImagePath": args.image_path,
        "Profile": args.profile,
        "Status": args.status,
    }
    fields = {k: v for k, v in field_map.items() if v is not None}
    if not fields:
        print("Nothing to write — pass at least one field flag.", file=sys.stderr)
        return 2

    try:
        rec = create_record(fields)
    except AirtableError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        print(rec["id"])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
