#!/usr/bin/env python3
"""
TikTok video generator using TokenRouter + MiniMax-Hailuo-2.3.

Generates a short video (default 10s) from a text prompt, with optional
first-frame reference image for character consistency.

Endpoint: https://api.tokenrouter.com/v1/video/generations (POST)
Status:    https://api.tokenrouter.com/v1/videos/{task_id} (GET, async)

Credentials: TOKENROUTER_API_KEY env var.

Usage (CLI):
    python tiktok_video_generator.py "a calico cat playing with a red ball"
    python tiktok_video_generator.py "Sasha waves at the camera" \
        --first-frame /path/to/sasha.png --duration 10 --upload

Usage (as a module):
    from tiktok_video_generator import generate_video

    info = generate_video("Sasha waves", first_frame_image="sasha.png", duration=10)
    print(info["url"])  # -> https://video-product.cdn.minimax.io/.../output.mp4
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


TOKENROUTER_BASE_URL = "https://api.tokenrouter.com/v1"
DEFAULT_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_DURATION = 10  # seconds
DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_MAX_WAIT = 600  # seconds (10 minutes)


class VideoGenError(Exception):
    """Raised when video generation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise VideoGenError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the generator."
        )
    return key


def _file_to_data_url(path: str | os.PathLike, mime: str = "image/png") -> str:
    """Read a local file and return a base64 data: URL."""
    p = Path(path)
    if not p.is_file():
        raise VideoGenError(f"File not found: {path}")
    blob = p.read_bytes()
    # Sniff actual format from magic bytes; allow caller override
    if mime == "image/png" and blob[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif blob[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        mime = "image/webp"
    b64 = base64.b64encode(blob).decode()
    return f"data:{mime};base64,{b64}"


def _normalize_first_frame(
    value: str | os.PathLike,
) -> str:
    """
    Accept: local file path, http(s) URL, or already-embedded data: URL.
    Returns: data: URL (so the API gets inline bytes — no extra fetch).
    """
    s = str(value)
    if s.startswith("data:") or s.startswith("http://") or s.startswith("https://"):
        return s
    return _file_to_data_url(s)


def _api_call(path: str, payload: Optional[dict] = None, method: str = "POST") -> dict:
    """Make an authenticated request to TokenRouter."""
    url = f"{TOKENROUTER_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise VideoGenError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise VideoGenError(f"Network error: {e}") from e


def generate_video(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = DEFAULT_DURATION,
    first_frame_image: Optional[str | os.PathLike] = None,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    max_wait: int = DEFAULT_MAX_WAIT,
    verbose: bool = True,
) -> dict:
    """
    Generate a short video from a text prompt and return the result dict.

    Args:
        prompt: Text description of the video.
        model: TokenRouter model ID. Default: MiniMax-Hailuo-2.3.
        duration: Video length in seconds. 10 is well-supported.
        first_frame_image: Optional local file path, http(s) URL, or data: URL.
            When provided, the model uses it as the first frame of the
            generated video — ideal for character consistency (the first
            frame IS your character's portrait, then the video animates from
            there). Accepts the same input forms as `tiktok_image_generator`.
        poll_interval: Seconds between status polls.
        max_wait: Maximum total wait time in seconds.
        verbose: If True, print progress to stderr.

    Returns:
        Dict containing the final API response: at minimum `id`, `status`,
        `model`, and `metadata.url` (the CDN URL of the generated MP4).

    Raises:
        VideoGenError: On any failure (missing key, API error, timeout).
    """
    if not prompt or not prompt.strip():
        raise VideoGenError("Prompt must not be empty.")

    payload = {
        "model": model,
        "prompt": prompt.strip(),
        "duration": duration,
    }
    if first_frame_image is not None:
        payload["first_frame_image"] = _normalize_first_frame(first_frame_image)

    if verbose:
        print(f"Submitting {model} video task ({duration}s)...", file=sys.stderr)

    submit = _api_call("/video/generations", payload)
    task_id = submit.get("id") or submit.get("task_id")
    if not task_id:
        raise VideoGenError(f"No task_id in submit response: {submit}")
    if verbose:
        print(f"  task_id: {task_id}", file=sys.stderr)

    # Poll until done
    deadline = time.time() + max_wait
    elapsed = 0
    while time.time() < deadline:
        time.sleep(poll_interval)
        elapsed += poll_interval
        result = _api_call(f"/videos/{task_id}", method="GET")
        status = result.get("status", "?")
        progress = result.get("progress", "?")
        url = (result.get("metadata") or {}).get("url", "")
        if verbose:
            print(f"  [{elapsed:3d}s] status={status} progress={progress}", file=sys.stderr)

        if status in ("completed", "succeeded", "done", "finished", "success"):
            if not url:
                raise VideoGenError(
                    f"Task completed but no URL in metadata: {result}"
                )
            if verbose:
                print(f"  ✓ {url}", file=sys.stderr)
            return result

        if status in ("failed", "error", "canceled", "cancelled"):
            raise VideoGenError(f"Task {task_id} {status}: {result}")

    raise VideoGenError(f"Task {task_id} did not complete within {max_wait}s")


def download_video(url: str, output: str | os.PathLike) -> Path:
    """Download the generated MP4 to a local file."""
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        out_path.write_bytes(r.read())
    return out_path


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a short TikTok video via TokenRouter + Hailuo 2.3."
    )
    parser.add_argument("prompt", help="Text description of the video")
    parser.add_argument(
        "--first-frame", "-f",
        default=None,
        metavar="PATH_OR_URL",
        help=(
            "Optional first-frame image (local path, http(s) URL, or data: URL). "
            "Used as the first frame of the generated video — ideal for character "
            "consistency (start with a portrait of your character)."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help=f"Video length in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--out", "-o", default=None, help="Local output file path (default: don't download, just print URL)")
    parser.add_argument("--upload", action="store_true", help="Also upload the local file to ImageKit and print the public URL")
    parser.add_argument("--folder", default="/tiktok-videos", help="ImageKit folder (used with --upload, default: /tiktok-videos)")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT, help=f"Max wait in seconds (default {DEFAULT_MAX_WAIT})")
    args = parser.parse_args()

    try:
        result = generate_video(
            args.prompt,
            model=args.model,
            duration=args.duration,
            first_frame_image=args.first_frame,
            max_wait=args.max_wait,
        )
    except VideoGenError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    cdn_url = result["metadata"]["url"]
    print(cdn_url)

    if args.out or args.upload:
        local_path = args.out or f"/tmp/{Path(urllib.parse.urlparse(cdn_url).path).name}"
        path = download_video(cdn_url, local_path)
        print(f"Downloaded: {path}", file=sys.stderr)

        if args.upload:
            try:
                from imagekit_uploader import upload_image, ImageKitError
            except ImportError as e:
                print(f"Cannot import imagekit_uploader: {e}", file=sys.stderr)
                return 1
            try:
                up = upload_image(str(path), folder=args.folder)
                print(f"ImageKit URL: {up['url']}")
            except ImageKitError as e:
                print(f"Upload error: {e}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
