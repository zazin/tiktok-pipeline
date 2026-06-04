#!/usr/bin/env python3
"""
TikTok upload step: ImageKit upload + Airtable record.

Takes a local image, uploads it to ImageKit (returning a public CDN URL), then
writes one Posts record to Airtable so the downstream tiktok-agent can pick it
up. This is the publish/log step that pairs with tiktok_image_generator.py
(which only generates the image now).

Credentials are read from the environment (or a local .env):
  - IMAGEKIT_PRIVATE_KEY                                       (ImageKit upload)
  - AIRTABLE_API_KEY / AIRTABLE_BASE_ID / AIRTABLE_TABLE_NAME  (Airtable record)

The Airtable Posts table must already exist (create it with airtable_migrate.py).

Usage (CLI):
    python tiktok_upload.py ./tiktok_output/x.png --idea "a cat in red boots" \
        --caption "..." --status pending
    python tiktok_upload.py ./x.png --no-airtable        # upload only

Usage (as a module):
    from tiktok_upload import upload_and_log

    result = upload_and_log("x.png", idea="...", caption="...")
    print(result["imagekit"]["url"], result["airtable"]["id"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


class UploadError(Exception):
    """Raised when the upload-and-log step fails."""


def upload_and_log(
    image_path: str | os.PathLike,
    *,
    folder: str = "/tiktok",
    idea: Optional[str] = None,
    caption: Optional[str] = None,
    description: Optional[str] = None,
    profile: Optional[str] = None,
    status: str = "pending",
    to_airtable: bool = True,
) -> dict:
    """
    Upload an image to ImageKit and (by default) log a Posts record to Airtable.

    Args:
        image_path: Local image file to upload.
        folder: ImageKit destination folder.
        idea: Airtable Idea field (primary).
        caption: Airtable Caption field.
        description: Airtable Description field.
        profile: Airtable Profile field.
        status: Airtable Status field (default "pending").
        to_airtable: When False, only upload to ImageKit and skip the record.

    Returns:
        {"imagekit": <upload dict>, "airtable": <record dict or None>}.

    Raises:
        UploadError: If the ImageKit upload or the Airtable write fails.
    """
    from imagekit_uploader import upload_image, ImageKitError

    path = Path(image_path)
    try:
        up = upload_image(str(path), folder=folder)
    except ImageKitError as e:
        raise UploadError(f"ImageKit upload failed: {e}") from e

    result = {"imagekit": up, "airtable": None}

    if to_airtable:
        from airtable_logger import create_record, AirtableError

        field_map = {
            "Idea": idea,
            "Caption": caption,
            "Description": description,
            "ImageURL": up.get("url"),
            "ImageKitFileId": up.get("fileId"),
            "ImagePath": path.name,
            "Profile": profile,
            "Status": status,
        }
        # Only send fields that have a value (besides Status, which defaults).
        fields = {k: v for k, v in field_map.items() if v is not None}
        try:
            result["airtable"] = create_record(fields)
        except AirtableError as e:
            raise UploadError(f"Airtable record failed: {e}") from e

    return result


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Upload an image to ImageKit and log a Posts record to Airtable."
    )
    parser.add_argument("image", help="Local image file to upload")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (default: /tiktok)")
    parser.add_argument("--idea", default=None, help="Airtable Idea field (primary)")
    parser.add_argument("--caption", default=None, help="Airtable Caption field")
    parser.add_argument("--description", default=None, help="Airtable Description field")
    parser.add_argument("--profile", default=None, help="Airtable Profile field")
    parser.add_argument("--status", default="pending", help="Airtable Status field (default: pending)")
    parser.add_argument("--no-airtable", action="store_true", help="Only upload to ImageKit; skip the Airtable record")
    parser.add_argument("--json", action="store_true", help="Print the full result JSON")
    args = parser.parse_args()

    try:
        result = upload_and_log(
            args.image,
            folder=args.folder,
            idea=args.idea,
            caption=args.caption,
            description=args.description,
            profile=args.profile,
            status=args.status,
            to_airtable=not args.no_airtable,
        )
    except UploadError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Public URL: {result['imagekit'].get('url')}")
        if result["airtable"]:
            print(f"Airtable record: {result['airtable']['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
