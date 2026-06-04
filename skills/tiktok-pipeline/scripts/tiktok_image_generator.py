#!/usr/bin/env python3
"""
TikTok image generator using TokenRouter.

Generates an image from a text prompt and saves it as a PNG file. Pairs
naturally with imagekit_uploader.py to publish the result.

Credentials are read from the environment:
  - TOKENROUTER_API_KEY

TokenRouter is OpenAI-compatible. Image generation is exposed via the chat
completions endpoint with `modalities: ["image", "text"]`. The image comes
back as a base64-encoded data URL in
`choices[0].message.images[0].image_url.url`.

Default model: google/gemini-2.5-flash-image (fast, good quality, cheap).
Other available image models on TokenRouter:
  - google/gemini-3-pro-image-preview
  - google/gemini-3.1-flash-image-preview
  - openai/gpt-5-image
  - openai/gpt-5-image-mini
  - openai/gpt-5.4-image-2

Usage (CLI):
    python tiktok_image_generator.py "a cat smiling wearing red boots"
    python tiktok_image_generator.py "neon skyline" --out skyline.png --model openai/gpt-5-image-mini
    python tiktok_image_generator.py "..." --upload  # also push to ImageKit

Usage (as a module):
    from tiktok_image_generator import generate_image

    path = generate_image("a cat smiling wearing red boots", output="cat.png")
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

from PIL import Image


TOKENROUTER_BASE_URL = "https://api.tokenrouter.com/v1"

# Default model: Gemini 3.1 Flash natively honors aspect_ratio and returns
# a portrait image (768x1376 ≈ 9:16) so no cropping is needed. Fast & cheap.
# Other options:
#   - google/gemini-3-pro-image-preview     (also native 9:16, higher quality, slower)
#   - google/gemini-2.5-flash-image         (only 1024x1024, needs Pillow crop)
#   - openai/gpt-5-image / gpt-5-image-mini (only 1024x1024, needs Pillow crop)
DEFAULT_MODEL = "google/gemini-3.1-flash-image-preview"

# Models that natively return 9:16 when asked. For these we skip cropping
# and only do a clean upscale to the target resolution.
NATIVE_PORTRAIT_MODELS = frozenset({
    "google/gemini-3-pro-image-preview",
    "google/gemini-3.1-flash-image-preview",
})

# TikTok recommended portrait resolution (9:16)
TIKTOK_WIDTH = 1080
TIKTOK_HEIGHT = 1920
ResizeMode = Literal["fit", "pad", "none"]

# TikTok-oriented prompt scaffold. The user's idea is plugged into {idea}.
# Vertical 9:16 framing is requested in text since these models don't accept
# an explicit size parameter on this endpoint.
TIKTOK_PROMPT_TEMPLATE = (
    "Create a high-quality vertical image (9:16 aspect ratio, portrait, "
    "1080x1920) suitable for a TikTok post. The subject: {idea}. "
    "Style: vivid colors, sharp focus, eye-catching composition, "
    "cinematic lighting. No text overlay, no watermark."
)


class ImageGenError(Exception):
    """Raised when image generation fails."""


class ImageRefusal(ImageGenError):
    """
    Raised when the model returned no usable image for an attempt — either an
    explicit refusal or an empty/imageless response. These are often transient
    (especially for reference-image edits of real faces), so generate_image
    retries on them.
    """


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise ImageGenError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the generator."
        )
    return key


# Auto-generated filenames use a consistent, chronologically sortable timestamp:
#   tiktok_YYYYMMDD_HHMMSS.<ext>   e.g. tiktok_20260604_141432.png
FILENAME_PREFIX = "tiktok"
FILENAME_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def _timestamped_path(out_dir: Path, ext: str) -> Path:
    """
    Build a consistent output path of the form tiktok_YYYYMMDD_HHMMSS.<ext>.

    If a file with that name already exists (multiple images generated within
    the same second), a `_N` counter is appended to keep names unique without
    breaking the timestamp format.
    """
    stamp = time.strftime(FILENAME_TIMESTAMP_FORMAT)
    candidate = out_dir / f"{FILENAME_PREFIX}_{stamp}.{ext}"
    counter = 1
    while candidate.exists():
        candidate = out_dir / f"{FILENAME_PREFIX}_{stamp}_{counter}.{ext}"
        counter += 1
    return candidate


def _extract_data_url(response: dict) -> str:
    """Pull the first image data URL out of a TokenRouter chat-completion response."""
    try:
        choice = response["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError) as e:
        raise ImageGenError(f"Unexpected response shape: {e}; body={str(response)[:300]}")

    # Preferred location: message.images[0].image_url.url
    images = msg.get("images") or []
    for item in images:
        if isinstance(item, dict):
            url = (item.get("image_url") or {}).get("url") or item.get("url")
            if url:
                return url

    # Fallback: content may be a list of parts including image_url
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("image_url", "image"):
                url = (part.get("image_url") or {}).get("url") or part.get("url")
                if url:
                    return url

    # No image. If the model explicitly refused, surface that reason; either way
    # this is treated as a (often transient) refusal that generate_image retries.
    refusal = msg.get("refusal")
    if refusal:
        raise ImageRefusal(f"Model refused to generate the image: {refusal}")
    raise ImageRefusal(
        "No image found in response. "
        f"message keys={list(msg.keys())}, content type={type(content).__name__}"
    )


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Return (raw_bytes, file_extension) from a data: URL."""
    m = re.match(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<b64>.+)$", data_url, re.DOTALL)
    if not m:
        # Sometimes the model returns a plain http(s) URL — fetch it
        if data_url.startswith("http"):
            with urllib.request.urlopen(data_url, timeout=60) as r:
                blob = r.read()
                mime = r.headers.get("Content-Type", "image/png").split(";")[0].strip()
                ext = mime.split("/")[-1] or "png"
                return blob, ext
        raise ImageGenError(f"Unrecognized image URL format: {data_url[:80]}...")
    mime = m.group("mime")
    ext = mime.split("/")[-1] or "png"
    blob = base64.b64decode(m.group("b64"))
    return blob, ext


# Models that support multi-modal image-input (reference photo) for object/
# product/face preservation. As of the last probe, all Gemini image models on
# TokenRouter accept reference images. GPT-5 image models also accept them.
REFERENCE_IMAGE_MODELS = frozenset({
    "google/gemini-2.5-flash-image",
    "google/gemini-3-pro-image-preview",
    "google/gemini-3.1-flash-image-preview",
    "openai/gpt-5-image",
    "openai/gpt-5-image-mini",
})

# "preserve" (default): the subject in the reference must remain visually
# the same in the output. Best for faces, branded products, logos.
# "feature": the reference shows an object that should APPEAR somewhere
# in the output. Best for "place this product in a scene" workflows where
# the output can be a wider shot.
RefKind = Literal["preserve", "feature"]

REF_PRESERVE_PROMPT_TEMPLATE = (
    "You are an image-to-image editor. The user has provided a reference image. "
    "Apply this transformation to it: {idea}. "
    "CRITICAL REQUIREMENTS: "
    "(1) Preserve the exact subject identity shown in the reference — this "
    "may be a person (face, skin, body), a branded product, a logo, an "
    "animal, or any other subject. Keep the recognizable details, colors, "
    "shapes, and distinctive features of the reference subject. "
    "(2) Do NOT generate a different subject — the subject in the output "
    "must be the SAME subject in a new scene/context. "
    "(3) Keep the subject clearly visible, well-lit, and centered in the frame. "
    "(4) Vertical 9:16 aspect ratio, portrait composition, 1080x1920. "
    "(5) Vivid colors, sharp focus, cinematic lighting. "
    "No text overlay, no watermark."
)

REF_FEATURE_PROMPT_TEMPLATE = (
    "You are an image composition assistant. The user has provided a reference "
    "image showing a specific subject (a person, product, animal, or object). "
    "Generate a new image: {idea}, and place the exact subject from the "
    "reference image into this scene. "
    "CRITICAL REQUIREMENTS: "
    "(1) The subject from the reference must appear in the output, with the "
    "same recognizable details (face, branding, color, shape, distinctive "
    "features) preserved. "
    "(2) The subject can be scaled/repositioned to fit naturally in the scene, "
    "but its identity must be unmistakable. "
    "(3) Vertical 9:16 aspect ratio, portrait composition, 1080x1920. "
    "(4) Vivid colors, sharp focus, cinematic lighting, natural placement. "
    "No text overlay, no watermark."
)

# Default maximum size for reference images (downscale huge photos before
# sending — saves bandwidth and respects provider limits).
MAX_REF_IMAGE_DIM = 1024


def _load_reference_image(ref: str | os.PathLike) -> dict:
    """
    Load a reference image and return a multimodal content part dict
    ({"type": "image_url", "image_url": {"url": <data_url>}}).

    Accepts:
      - Local file path
      - http:// or https:// URL
      - Already-embedded data: URL (returned as-is)

    Resizes the image to fit within MAX_REF_IMAGE_DIM on the longest side
    and re-encodes as JPEG to keep payload size small. JPEG quality 90
    preserves facial detail well for face-preservation work.
    """
    ref_str = str(ref)
    mime = "image/jpeg"

    if ref_str.startswith("data:"):
        return {"type": "image_url", "image_url": {"url": ref_str}}

    if ref_str.startswith("http://") or ref_str.startswith("https://"):
        with urllib.request.urlopen(ref_str, timeout=60) as r:
            blob = r.read()
    else:
        path = Path(ref_str)
        if not path.is_file():
            raise ImageGenError(f"Reference image not found: {path}")
        blob = path.read_bytes()

    # Decode, downscale, re-encode as JPEG via Pillow
    try:
        with Image.open(BytesIO(blob)) as img:
            img = img.convert("RGB")
            longest = max(img.size)
            if longest > MAX_REF_IMAGE_DIM:
                scale = MAX_REF_IMAGE_DIM / longest
                new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
                img = img.resize(new_size, Image.LANCZOS)
            out_buf = BytesIO()
            img.save(out_buf, format="JPEG", quality=90)
            b64 = base64.b64encode(out_buf.getvalue()).decode()
    except Exception as e:
        raise ImageGenError(f"Could not process reference image {ref_str}: {e}") from e

    data_url = f"data:{mime};base64,{b64}"
    return {"type": "image_url", "image_url": {"url": data_url}}


def _resize_for_tiktok(
    src_path: Path,
    *,
    mode: ResizeMode = "fit",
    width: int = TIKTOK_WIDTH,
    height: int = TIKTOK_HEIGHT,
    pad_color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    """
    Resize an image in place to the TikTok target resolution (default 1080x1920).

    Modes:
      - "fit" : center-crop to the target aspect ratio, then resize. Fills the
                full frame, may discard edge pixels. Best for portraits.
      - "pad" : scale the whole image to fit inside the frame, then pad the
                rest with `pad_color`. No pixels lost, may show bars.
      - "none": skip resizing entirely.
    """
    if mode == "none":
        return

    with Image.open(src_path) as img:
        img = img.convert("RGB")
        target_aspect = width / height
        src_w, src_h = img.size
        src_aspect = src_w / src_h

        # If the model already produced (close to) the right aspect, skip
        # cropping and just resize. This is the common case for native-portrait
        # models like Gemini 3.x which return 768x1376 ≈ 9:16.
        if abs(src_aspect - target_aspect) < 0.02:
            out = img.resize((width, height), Image.LANCZOS)
            out.save(src_path, format="PNG", optimize=True)
            return

        if mode == "fit":
            # Center-crop to target aspect ratio, then resize
            if src_aspect > target_aspect:
                # Source is too wide — crop sides
                new_w = int(src_h * target_aspect)
                left = (src_w - new_w) // 2
                box = (left, 0, left + new_w, src_h)
            else:
                # Source is too tall — crop top/bottom
                new_h = int(src_w / target_aspect)
                top = (src_h - new_h) // 2
                box = (0, top, src_w, top + new_h)
            cropped = img.crop(box)
            out = cropped.resize((width, height), Image.LANCZOS)

        elif mode == "pad":
            # Scale to fit, then paste onto a canvas of target size
            if src_aspect > target_aspect:
                new_w = width
                new_h = int(width / src_aspect)
            else:
                new_h = height
                new_w = int(height * src_aspect)
            scaled = img.resize((new_w, new_h), Image.LANCZOS)
            out = Image.new("RGB", (width, height), pad_color)
            out.paste(scaled, ((width - new_w) // 2, (height - new_h) // 2))

        else:
            raise ImageGenError(f"Unknown resize mode: {mode}")

        out.save(src_path, format="PNG", optimize=True)


def generate_image(
    prompt: str,
    *,
    output: Optional[str | os.PathLike] = None,
    model: str = DEFAULT_MODEL,
    style_template: Optional[str] = TIKTOK_PROMPT_TEMPLATE,
    timeout: int = 240,
    output_dir: str | os.PathLike = "tiktok_output",
    resize: ResizeMode = "fit",
    width: int = TIKTOK_WIDTH,
    height: int = TIKTOK_HEIGHT,
    reference_image: Optional[str | os.PathLike] = None,
    reference_kind: RefKind = "preserve",
    retries: int = 2,
    retry_delay: float = 2.0,
) -> Path:
    """
    Generate an image from a text prompt and save it to disk.

    Args:
        prompt: User's idea (e.g. "a cat smiling wearing red boots").
        output: Output path. If None, a timestamped name is created under
            `output_dir`.
        model: TokenRouter model ID. Must be an image-capable model.
        style_template: Optional wrapper template with a `{idea}` placeholder.
            Pass None to use the raw prompt verbatim.
        timeout: HTTP timeout in seconds.
        output_dir: Directory used when `output` is None.
        reference_image: Optional reference image — local path, http(s) URL,
            or data: URL. The image can be a face, a product, an animal,
            a logo, an object — anything. The model receives it as a
            multi-modal input and includes it in the output:
              * reference_kind="preserve" (default): the subject stays
                visually the same (face/product identity preserved).
              * reference_kind="feature": the subject is placed into a new
                scene (allowed to be scaled/repositioned).
        reference_kind: See above. Ignored if reference_image is None.
        retries: Number of extra attempts if the model returns no image /
            refuses (total attempts = retries + 1). Default 2.
        retry_delay: Seconds to wait between retry attempts.

    Returns:
        Path to the saved image file.

    Raises:
        ImageGenError: On any failure (missing key, API error, decode error,
            or model that does not support reference images).
    """
    if not prompt or not prompt.strip():
        raise ImageGenError("Prompt must not be empty.")

    use_ref = reference_image is not None
    if use_ref and model not in REFERENCE_IMAGE_MODELS:
        raise ImageGenError(
            f"Model {model!r} does not support reference images. "
            f"Use one of: {sorted(REFERENCE_IMAGE_MODELS)}"
        )

    # Pick the right template and build the user message
    if use_ref:
        template = (
            REF_PRESERVE_PROMPT_TEMPLATE
            if reference_kind == "preserve"
            else REF_FEATURE_PROMPT_TEMPLATE
        )
        full_prompt = template.format(idea=prompt.strip())
        # _load_reference_image accepts a single ref, but a list would work too
        # — this keeps the function signature future-proof.
        refs = reference_image if isinstance(reference_image, list) else [reference_image]
        user_content = [{"type": "text", "text": full_prompt}]
        for ref in refs:
            user_content.append(_load_reference_image(ref))
    else:
        full_prompt = (
            style_template.format(idea=prompt.strip())
            if style_template else prompt.strip()
        )
        user_content = full_prompt

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": ["image", "text"],
        # Hint native-portrait models to render 9:16 directly. Models that
        # don't understand this just ignore it.
        "aspect_ratio": f"{width}:{height}" if width and height else "9:16",
        "size": f"{width}x{height}",
    }
    body = json.dumps(payload).encode()
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }

    # Send + extract, retrying on refusals / imageless responses (these are
    # often transient, especially for reference-image edits of real faces).
    data_url = None
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            f"{TOKENROUTER_BASE_URL}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp_bytes = r.read()
            response = json.loads(resp_bytes)
            if "error" in response:
                raise ImageGenError(f"API error: {response['error']}")
            data_url = _extract_data_url(response)
            break  # success
        except ImageRefusal as e:
            if attempt >= attempts:
                raise ImageRefusal(f"{e} (after {attempts} attempt(s))") from e
            print(
                f"Image attempt {attempt}/{attempts} got no image ({e}); retrying...",
                file=sys.stderr,
            )
            time.sleep(retry_delay)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            raise ImageGenError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
        except urllib.error.URLError as e:
            raise ImageGenError(f"Network error: {e}") from e
        except json.JSONDecodeError as e:
            raise ImageGenError(f"Invalid JSON response: {e}") from e

    blob, ext = _decode_data_url(data_url)

    # Resolve output path
    if output is None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = _timestamped_path(out_dir, ext)
    else:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_bytes(blob)
    _resize_for_tiktok(out_path, mode=resize, width=width, height=height)
    return out_path


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Generate a TikTok-style image from a text prompt via TokenRouter."
    )
    parser.add_argument("prompt", help='Text idea, e.g. "a cat smiling wearing red boots"')
    parser.add_argument("--out", "-o", default=None, help="Output file path (default: tiktok_output/tiktok_YYYYMMDD_HHMMSS.<ext>)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--raw-prompt", action="store_true", help="Use the prompt as-is without the TikTok style template")
    parser.add_argument("--retries", type=int, default=2, help="Extra attempts on a model refusal / no-image response (default: 2)")
    parser.add_argument(
        "--resize",
        choices=["fit", "pad", "none"],
        default="fit",
        help="Resize strategy: 'fit' center-crops to 9:16 (default), 'pad' letterboxes, 'none' keeps source",
    )
    parser.add_argument("--width", type=int, default=TIKTOK_WIDTH, help=f"Target width (default {TIKTOK_WIDTH})")
    parser.add_argument("--height", type=int, default=TIKTOK_HEIGHT, help=f"Target height (default {TIKTOK_HEIGHT})")
    parser.add_argument("--upload", action="store_true", help="Also upload the result to ImageKit and print the public URL")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (used with --upload, default: /tiktok)")
    parser.add_argument(
        "--ref",
        dest="ref",
        default=None,
        metavar="PATH_OR_URL",
        help=(
            "Reference image to include in the output. Local file path or "
            "http(s) URL. Can be a face, a product, a logo, an object — "
            "any subject. The model receives it as a multi-modal input."
        ),
    )
    parser.add_argument(
        "--ref-kind",
        dest="ref_kind",
        default="preserve",
        choices=["preserve", "feature"],
        help=(
            "How the reference should appear in the output. "
            "'preserve' (default): keep the subject visually identical "
            "(best for faces, branded products). "
            "'feature': place the subject in a new scene, allowed to be "
            "scaled/repositioned (best for 'put this product in a setting')."
        ),
    )
    args = parser.parse_args()

    try:
        path = generate_image(
            args.prompt,
            output=args.out,
            model=args.model,
            style_template=None if args.raw_prompt else TIKTOK_PROMPT_TEMPLATE,
            resize=args.resize,
            width=args.width,
            height=args.height,
            reference_image=args.ref,
            reference_kind=args.ref_kind,
            retries=args.retries,
        )
    except ImageGenError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Saved: {path}")

    if args.upload:
        try:
            from imagekit_uploader import upload_image, ImageKitError
        except ImportError as e:
            print(f"Cannot import imagekit_uploader: {e}", file=sys.stderr)
            return 1
        try:
            result = upload_image(str(path), folder=args.folder)
            print(f"Public URL: {result['url']}")
        except ImageKitError as e:
            print(f"Upload error: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
