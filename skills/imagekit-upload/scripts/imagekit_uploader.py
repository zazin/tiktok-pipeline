#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
ImageKit uploader module.

Uploads images to ImageKit as public files and returns their public URLs.

Credentials are read from environment variables:
  - IMAGEKIT_PUBLIC_KEY
  - IMAGEKIT_PRIVATE_KEY

URL endpoint: https://ik.imagekit.io/salt/

Usage (CLI):
    python imagekit_uploader.py path/to/image.png
    python imagekit_uploader.py path/to/image.png --folder /banners --name hero
    python imagekit_uploader.py ./images/*.jpg --folder /gallery

Usage (as a module):
    from imagekit_uploader import upload_image

    result = upload_image("photo.jpg", folder="/products")
    print(result["url"])
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Optional

import requests


IMAGEKIT_UPLOAD_URL = "https://upload.imagekit.io/api/v1/files/upload"
IMAGEKIT_URL_ENDPOINT = "https://ik.imagekit.io/salt/"


class ImageKitError(Exception):
    """Raised when an ImageKit upload fails."""


def _get_private_key() -> str:
    key = os.getenv("IMAGEKIT_PRIVATE_KEY")
    if not key:
        raise ImageKitError(
            "IMAGEKIT_PRIVATE_KEY env var is not set. "
            "Export it before running the uploader."
        )
    return key


def _auth_header(private_key: str) -> dict:
    # ImageKit uses HTTP Basic auth with the private key as username and empty password
    token = base64.b64encode(f"{private_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def upload_image(
    image_path: str | os.PathLike,
    *,
    file_name: Optional[str] = None,
    folder: str = "/",
    use_unique_file_name: bool = True,
    tags: Optional[list[str]] = None,
    custom_metadata: Optional[dict] = None,
    timeout: int = 60,
) -> dict:
    """
    Upload a single image to ImageKit as a public file.

    Args:
        image_path: Local path to the image file.
        file_name: Name to store the file under on ImageKit. Defaults to the
            local file's name.
        folder: Destination folder on ImageKit (e.g. "/banners"). Defaults to root.
        use_unique_file_name: If True, ImageKit appends a unique suffix to
            avoid collisions. Set False to overwrite by name.
        tags: Optional list of tags to attach to the asset.
        custom_metadata: Optional dict of ImageKit custom-metadata fields
            (e.g. {"caption": ..., "description": ...}). The fields must already
            exist in the ImageKit account's custom-metadata schema.
        timeout: Request timeout in seconds.

    Returns:
        Dict containing at minimum: fileId, name, url (public URL), filePath,
        thumbnailUrl, width, height, size, fileType. See ImageKit docs for the
        full response shape.

    Raises:
        ImageKitError: On any failure (missing creds, network error, API error).
    """
    path = Path(image_path)
    if not path.is_file():
        raise ImageKitError(f"File not found: {path}")

    private_key = _get_private_key()
    name = file_name or path.name
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"

    with path.open("rb") as fh:
        files = {"file": (name, fh, mime)}
        data = {
            "fileName": name,
            "folder": folder,
            "useUniqueFileName": "true" if use_unique_file_name else "false",
            # isPrivateFile=false means publicly accessible
            "isPrivateFile": "false",
        }
        if tags:
            data["tags"] = ",".join(tags)
        if custom_metadata:
            data["customMetadata"] = json.dumps(custom_metadata)

        try:
            resp = requests.post(
                IMAGEKIT_UPLOAD_URL,
                files=files,
                data=data,
                headers=_auth_header(private_key),
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise ImageKitError(f"Network error uploading {path}: {e}") from e

    if resp.status_code != 200:
        # ImageKit returns JSON errors; fall back to raw text
        try:
            err = resp.json().get("message", resp.text)
        except ValueError:
            err = resp.text
        raise ImageKitError(f"Upload failed (HTTP {resp.status_code}): {err}")

    return resp.json()


def upload_images(
    paths: list[str | os.PathLike],
    *,
    folder: str = "/",
    use_unique_file_name: bool = True,
    tags: Optional[list[str]] = None,
) -> list[dict]:
    """
    Upload multiple images. Returns a list of result dicts, one per path.

    Each entry has either {"status": "success", **api_response} or
    {"status": "failed", "path": str, "error": str} so a single failure
    does not abort the whole batch.
    """
    results: list[dict] = []
    for p in paths:
        try:
            data = upload_image(
                p,
                folder=folder,
                use_unique_file_name=use_unique_file_name,
                tags=tags,
            )
            results.append({"status": "success", "path": str(p), **data})
        except ImageKitError as e:
            results.append({"status": "failed", "path": str(p), "error": str(e)})
    return results


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Upload image(s) to ImageKit as public files."
    )
    parser.add_argument("paths", nargs="+", help="Image file path(s) to upload")
    parser.add_argument(
        "--folder",
        default="/tiktok",
        help="Destination folder on ImageKit (default: /tiktok)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Override file name (single-file uploads only)",
    )
    parser.add_argument(
        "--tags",
        default=None,
        help="Comma-separated tags to attach",
    )
    parser.add_argument(
        "--no-unique",
        action="store_true",
        help="Disable unique file name suffix (overwrite by name)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON response instead of just URL(s)",
    )
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    try:
        if len(args.paths) == 1:
            result = upload_image(
                args.paths[0],
                file_name=args.name,
                folder=args.folder,
                use_unique_file_name=not args.no_unique,
                tags=tags,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(result["url"])
            return 0

        if args.name:
            print("--name only applies to single-file uploads", file=sys.stderr)
            return 2

        results = upload_images(
            args.paths,
            folder=args.folder,
            use_unique_file_name=not args.no_unique,
            tags=tags,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                if r["status"] == "success":
                    print(r["url"])
                else:
                    print(f"FAILED {r['path']}: {r['error']}", file=sys.stderr)
        failed = sum(1 for r in results if r["status"] == "failed")
        return 1 if failed else 0

    except ImageKitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
