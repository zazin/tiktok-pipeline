#!/usr/bin/env python3
"""
TikTok auto-uploader pipeline — the top-level "app".

Runs the whole flow end to end:

    1. AI invents a TikTok image idea         (idea_generator.generate_idea)
    2. Generate a 9:16 image from that idea    (tiktok_image_generator.generate_image)
    3. Deliver it to both targets, independently:
         - push to an Android phone over USB    (phone_uploader.push_to_phone)
         - upload to ImageKit CDN               (imagekit_uploader.upload_image)

A failure in one delivery target does NOT abort the other. Pass --prompt to skip
the AI idea step and use your own prompt, or --no-phone / --no-imagekit to skip a
delivery target.

All generated images are saved into one folder (default: tiktok_output/), so the
whole run history is kept in one place.

Credentials (read from the environment, depending on which steps run):
  - TOKENROUTER_API_KEY   (AI idea step + image generation — both via TokenRouter)
  - IMAGEKIT_PRIVATE_KEY  (ImageKit upload, unless --no-imagekit)
  - IMAGEKIT_PUBLIC_KEY   (ImageKit upload, unless --no-imagekit)

Usage (CLI):
    # Fully automatic: AI idea -> image -> phone + ImageKit
    python tiktok_pipeline.py

    # Steer the idea by theme
    python tiktok_pipeline.py --theme "cyberpunk street food"

    # Bring your own prompt, ImageKit only (no phone connected)
    python tiktok_pipeline.py --prompt "neon skyline at dusk" --no-phone

Usage (as a module):
    from tiktok_pipeline import run_pipeline
    result = run_pipeline(theme="cozy coffee")
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def run_pipeline(
    *,
    prompt: Optional[str] = None,
    theme: Optional[str] = None,
    model: Optional[str] = None,
    idea_model: Optional[str] = None,
    output: Optional[str] = None,
    output_dir: str = "tiktok_output",
    resize: str = "fit",
    width: Optional[int] = None,
    height: Optional[int] = None,
    reference_image: Optional[str] = None,
    reference_kind: str = "preserve",
    to_phone: bool = True,
    phone_dest: Optional[str] = None,
    phone_serial: Optional[str] = None,
    to_imagekit: bool = True,
    imagekit_folder: str = "/tiktok",
) -> dict:
    """
    Run the full generate-and-deliver pipeline for a single image.

    Returns a result dict:
        {
          "idea": str,
          "path": str,
          "phone": {"status": "success"|"failed"|"skipped", "remote"/"error": ...},
          "imagekit": {"status": "success"|"failed"|"skipped", "url"/"error": ...},
        }

    Raises:
        Exception subclasses from the idea/generation steps only — those are
        fatal. Delivery failures are captured in the result dict, not raised.
    """
    # Lazy imports so a missing optional dependency (anthropic / adb) or missing
    # creds only break the step that actually needs them.
    from tiktok_image_generator import generate_image, ImageGenError, DEFAULT_MODEL

    # --- 1. Idea ---------------------------------------------------------
    if prompt and prompt.strip():
        idea = prompt.strip()
        print(f"Idea (manual): {idea}")
    else:
        from idea_generator import generate_idea, DEFAULT_MODEL as IDEA_MODEL
        idea = generate_idea(theme=theme, model=idea_model or IDEA_MODEL)
        print(f"Idea (AI): {idea}")

    # --- 2. Generate -----------------------------------------------------
    # Make sure the image storage folder exists (generate_image also creates it
    # when picking an auto name, but we ensure it up front so it always exists).
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    gen_kwargs = {
        "output": output,
        "output_dir": output_dir,
        "model": model or DEFAULT_MODEL,
        "resize": resize,
        "reference_image": reference_image,
        "reference_kind": reference_kind,
    }
    if width:
        gen_kwargs["width"] = width
    if height:
        gen_kwargs["height"] = height

    path: Path = generate_image(idea, **gen_kwargs)  # ImageGenError is fatal
    print(f"Generated: {path}")

    result: dict = {
        "idea": idea,
        "path": str(path),
        "phone": {"status": "skipped"},
        "imagekit": {"status": "skipped"},
    }

    # --- 3a. Deliver: phone (non-fatal) ----------------------------------
    if to_phone:
        try:
            from phone_uploader import push_to_phone, PhonePushError
            kwargs = {"serial": phone_serial}
            if phone_dest:
                kwargs["dest_dir"] = phone_dest
            remote = push_to_phone(str(path), **kwargs)
            result["phone"] = {"status": "success", "remote": remote}
            print(f"Phone: pushed -> {remote}")
        except Exception as e:  # PhonePushError or import error
            result["phone"] = {"status": "failed", "error": str(e)}
            print(f"Phone: FAILED — {e}", file=sys.stderr)

    # --- 3b. Deliver: ImageKit (non-fatal) -------------------------------
    if to_imagekit:
        try:
            from imagekit_uploader import upload_image, ImageKitError
            data = upload_image(str(path), folder=imagekit_folder)
            url = data.get("url", "")
            result["imagekit"] = {"status": "success", "url": url}
            print(f"ImageKit: {url}")
        except Exception as e:  # ImageKitError or import error
            result["imagekit"] = {"status": "failed", "error": str(e)}
            print(f"ImageKit: FAILED — {e}", file=sys.stderr)

    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-generate a TikTok image and deliver it to phone + ImageKit."
    )
    # Idea / generation
    parser.add_argument("--prompt", default=None, help="Use this exact prompt instead of an AI-generated idea")
    parser.add_argument("--theme", default=None, help="Theme to steer the AI idea (ignored if --prompt is set)")
    parser.add_argument("--model", default=None, help="TokenRouter image model ID (default: generator's default)")
    parser.add_argument("--idea-model", default=None, help="TokenRouter Anthropic model for idea generation (default: anthropic/claude-haiku-4.5)")
    parser.add_argument("--out", "-o", default=None, help="Exact output image path (overrides --output-dir auto-naming)")
    parser.add_argument("--output-dir", default="tiktok_output", help="Folder to store generated images (default: tiktok_output/)")
    parser.add_argument("--resize", choices=["fit", "pad", "none"], default="fit", help="Resize strategy (default: fit)")
    parser.add_argument("--width", type=int, default=None, help="Target width (default: generator's 1080)")
    parser.add_argument("--height", type=int, default=None, help="Target height (default: generator's 1920)")
    parser.add_argument("--ref", dest="ref", default=None, metavar="PATH_OR_URL", help="Reference image (face/product/logo) to include")
    parser.add_argument("--ref-kind", dest="ref_kind", choices=["preserve", "feature"], default="preserve", help="How the reference appears (default: preserve)")
    # Delivery: phone
    parser.add_argument("--no-phone", action="store_true", help="Skip pushing to the Android phone")
    parser.add_argument("--dest", default=None, help="Remote dir on the phone (default: /sdcard/Pictures)")
    parser.add_argument("--serial", default=None, help="Target device serial (if multiple phones connected)")
    # Delivery: ImageKit
    parser.add_argument("--no-imagekit", action="store_true", help="Skip uploading to ImageKit")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (default: /tiktok)")
    args = parser.parse_args()

    try:
        result = run_pipeline(
            prompt=args.prompt,
            theme=args.theme,
            model=args.model,
            idea_model=args.idea_model,
            output=args.out,
            output_dir=args.output_dir,
            resize=args.resize,
            width=args.width,
            height=args.height,
            reference_image=args.ref,
            reference_kind=args.ref_kind,
            to_phone=not args.no_phone,
            phone_dest=args.dest,
            phone_serial=args.serial,
            to_imagekit=not args.no_imagekit,
            imagekit_folder=args.folder,
        )
    except Exception as e:
        # Fatal: idea or image-generation failure.
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # --- 4. Summary + exit code -----------------------------------------
    phone = result["phone"]["status"]
    ik = result["imagekit"]["status"]
    print("\n--- Summary ---")
    print(f"idea:     {result['idea']}")
    print(f"image:    {result['path']}")
    print(f"phone:    {phone}" + (f" ({result['phone'].get('remote','')})" if phone == "success" else ""))
    print(f"imagekit: {ik}" + (f" ({result['imagekit'].get('url','')})" if ik == "success" else ""))

    # Non-zero only if every requested delivery target failed.
    requested = [s for s in (phone, ik) if s != "skipped"]
    if requested and all(s == "failed" for s in requested):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
