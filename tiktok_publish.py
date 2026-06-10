#!/usr/bin/env python3
"""
TikTok publish step: ImageKit upload + HiveMQ publish.

Takes a local image, uploads it to ImageKit (returning a public CDN URL), then
publishes the post (idea, caption, description, the ImageKit URL + fileId, the
image filename, profile, status) as a HiveMQ message. The downstream tiktok-agent
subscribes to that topic and does the actual TikTok posting — so this is the
"publish to TikTok" step from this repo's side. Pairs with tiktok_image_generator.py
(which only generates the local image now).

Credentials are read from the environment (or a local .env):
  - IMAGEKIT_PRIVATE_KEY                              (ImageKit upload)
  - HIVEMQ_HOST / HIVEMQ_USERNAME / HIVEMQ_PASSWORD   (HiveMQ publish)
  - TIKTOK_ACCOUNT                                    (optional) TikTok @handle
                                                      to include as the
                                                      "Account" field in the
                                                      published post. The
                                                      agent switches to it
                                                      before posting. See
                                                      tiktok-agent
                                                      docs/post-image.md.

Usage (CLI):
    python tiktok_publish.py ./tiktok_output/x.png --idea "a cat in red boots" \
        --caption "..." --status pending
    python tiktok_publish.py ./x.png --no-hivemq        # upload only

Usage (as a module):
    from tiktok_publish import upload_and_publish

    result = upload_and_publish("x.png", idea="...", caption="...")
    print(result["imagekit"]["url"], result["hivemq"]["topic"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


class UploadError(Exception):
    """Raised when the upload-and-publish step fails."""


def upload_and_publish(
    image_path: str | os.PathLike,
    *,
    folder: str = "/tiktok",
    idea: Optional[str] = None,
    caption: Optional[str] = None,
    description: Optional[str] = None,
    profile: Optional[str] = None,
    account: Optional[str] = None,
    status: str = "pending",
    unique_file_name: bool = False,
    to_hivemq: bool = True,
) -> dict:
    """
    Upload an image to ImageKit and publish the post to HiveMQ.

    Args:
        image_path: Local image file to upload.
        folder: ImageKit destination folder.
        idea: Post idea (primary field).
        caption: Post caption.
        description: Post description.
        profile: Profile name (sets the `Profile` field in the published
            message; the profile itself is NOT loaded here). Independent of
            Account resolution — set TIKTOK_ACCOUNT (or --account) for the
            @handle.
        account: TikTok @handle (e.g. "@captgani") to include as the "Account"
            field. Wins over the TIKTOK_ACCOUNT env var. The downstream
            tiktok-agent switches to this account in-app before posting; if
            it can't be made active, the agent reports "wrong_account" and
            does not post. Omit / None / empty = do not include the field
            (the agent posts as the currently-active account).
        status: Post status (default "pending").
        unique_file_name: When False (default), the file keeps its exact name on
            ImageKit (generated names are already timestamped/unique, so this gives
            clean, valid filenames). Set True to let ImageKit append a random
            suffix (which can include a leading dash, e.g. "name_-Ab12.png").
        to_hivemq: When False, only upload to ImageKit and skip the HiveMQ publish.

    Returns:
        {"imagekit": <upload dict>, "hivemq": <publish dict or None>}.

    Raises:
        UploadError: If the ImageKit upload fails. A HiveMQ publish failure is
            non-fatal — it is captured in the result dict.
    """
    from imagekit_uploader import upload_image, ImageKitError

    path = Path(image_path)
    try:
        up = upload_image(str(path), folder=folder, use_unique_file_name=unique_file_name)
    except ImageKitError as e:
        raise UploadError(f"ImageKit upload failed: {e}") from e

    result = {"imagekit": up, "hivemq": None}

    if to_hivemq:
        # Resolve Account: --account > TIKTOK_ACCOUNT env > omit. An empty
        # value from any source is treated the same as missing — we never
        # send "Account": "".
        from hivemq_publisher import publish_post, resolve_account
        resolved_account = resolve_account(explicit=account)
        field_map = {
            "Idea": idea,
            "Caption": caption,
            "Description": description,
            "ImageURL": up.get("url"),
            "ImageKitFileId": up.get("fileId"),
            # The name ImageKit actually stored it under (matches ImageURL),
            # not the local filename — so the message always references the real file.
            "ImagePath": up.get("name") or path.name,
            "Profile": profile,
            "Account": resolved_account or None,
            "Status": status,
        }
        # Only send fields that have a value (besides Status, which defaults).
        payload = {k: v for k, v in field_map.items() if v is not None}
        try:
            result["hivemq"] = publish_post(payload)
        except Exception as e:  # HiveMQError or import error — non-fatal
            result["hivemq"] = {"status": "failed", "error": str(e)}
            print(f"HiveMQ: FAILED — {e}", file=sys.stderr)

    return result


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Upload an image to ImageKit and publish the post to HiveMQ."
    )
    parser.add_argument("image", help="Local image file to upload")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (default: /tiktok)")
    parser.add_argument("--idea", default=None, help="Post idea (primary field)")
    parser.add_argument("--caption", default=None, help="Post caption")
    parser.add_argument("--description", default=None, help="Post description")
    parser.add_argument("--profile", default=None, help="Profile name (sets the Profile field in the published message)")
    parser.add_argument("--account", default=None, help="TikTok @handle (e.g. @captgani) — agent switches account before posting. Default: TIKTOK_ACCOUNT env var, else omitted.")
    parser.add_argument("--status", default="pending", help="Post status (default: pending)")
    parser.add_argument("--unique", action="store_true", help="Let ImageKit append a random suffix to the file name (off by default — names are kept clean/exact)")
    parser.add_argument("--no-hivemq", action="store_true", help="Only upload to ImageKit; skip the HiveMQ publish")
    parser.add_argument("--json", action="store_true", help="Print the full result JSON")
    args = parser.parse_args()

    try:
        result = upload_and_publish(
            args.image,
            folder=args.folder,
            idea=args.idea,
            caption=args.caption,
            description=args.description,
            profile=args.profile,
            account=args.account,
            status=args.status,
            unique_file_name=args.unique,
            to_hivemq=not args.no_hivemq,
        )
    except UploadError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Public URL: {result['imagekit'].get('url')}")
        if result["hivemq"] and result["hivemq"].get("status") == "success":
            print(f"HiveMQ topic: {result['hivemq']['topic']}")

    # Non-zero exit if the HiveMQ publish was requested but failed.
    if result["hivemq"] and result["hivemq"].get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
