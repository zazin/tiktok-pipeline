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
    caption: bool = True,
    caption_model: Optional[str] = None,
    output: Optional[str] = None,
    output_dir: str = "tiktok_output",
    resize: str = "fit",
    width: Optional[int] = None,
    height: Optional[int] = None,
    reference_image: Optional[str] = None,
    reference_kind: str = "preserve",
    image_retries: int = 2,
    profile: Optional[str] = None,
    profiles_dir: Optional[str] = None,
    seed: Optional[int] = None,
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

    # --- 0. Profile (optional) -------------------------------------------
    # A profile supplies a persona (steers idea + caption) and reference
    # image(s) that preserve the person's identity in the generated image.
    persona = None
    variety = None
    if profile:
        from profile_loader import load_profile  # ProfileError is fatal
        prof = load_profile(profile, profiles_dir=profiles_dir)
        persona = prof["persona"]
        variety = prof.get("variety")
        # Profile reference images take precedence over any explicit --ref.
        reference_image = prof["reference_paths"]
        reference_kind = prof["reference_kind"]
        print(f"Profile: {prof['name']} ({len(reference_image)} reference image(s), kind={reference_kind})")

    # --- 1. Idea ---------------------------------------------------------
    if prompt and prompt.strip():
        idea = prompt.strip()
        print(f"Idea (manual): {idea}")
    else:
        from idea_generator import generate_idea, DEFAULT_MODEL as IDEA_MODEL
        idea = generate_idea(
            theme=theme, persona=persona, variety=variety, seed=seed,
            model=idea_model or IDEA_MODEL,
        )
        print(f"Idea (AI): {idea}")

    # --- 1b. Caption (separate text-only AI call, BEFORE the image) -------
    # Generated up front so it can be attached to the ImageKit upload as
    # custom metadata. Non-fatal: a caption failure must not block the image.
    caption_text = ""
    description_text = ""
    if caption:
        try:
            from caption_generator import generate_caption, DEFAULT_MODEL as CAP_MODEL
            cap = generate_caption(idea, persona=persona, model=caption_model or CAP_MODEL)
            caption_text = cap.get("caption", "")
            description_text = cap.get("description", "")
            print(f"Caption: {caption_text}")
        except Exception as e:  # CaptionError or import error
            print(f"Caption: FAILED — {e}", file=sys.stderr)

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
        "retries": image_retries,
    }
    if width:
        gen_kwargs["width"] = width
    if height:
        gen_kwargs["height"] = height

    path: Path = generate_image(idea, **gen_kwargs)  # ImageGenError is fatal
    print(f"Generated: {path}")

    result: dict = {
        "idea": idea,
        "caption": caption_text,
        "description": description_text,
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
            cm = {}
            if caption_text:
                cm["caption"] = caption_text
            if description_text:
                cm["description"] = description_text
            data = upload_image(
                str(path),
                folder=imagekit_folder,
                custom_metadata=cm or None,
            )
            url = data.get("url", "")
            result["imagekit"] = {"status": "success", "url": url}
            print(f"ImageKit: {url}")
        except Exception as e:  # ImageKitError or import error
            result["imagekit"] = {"status": "failed", "error": str(e)}
            print(f"ImageKit: FAILED — {e}", file=sys.stderr)

    return result


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Auto-generate a TikTok image and deliver it to phone + ImageKit."
    )
    # Idea / generation
    parser.add_argument("--prompt", default=None, help="Use this exact prompt instead of an AI-generated idea")
    parser.add_argument("--theme", default=None, help="Theme to steer the AI idea (ignored if --prompt is set)")
    parser.add_argument("--model", default=None, help="TokenRouter image model ID (default: generator's default)")
    parser.add_argument("--idea-model", default=None, help="TokenRouter Anthropic model for idea generation (default: anthropic/claude-haiku-4.5)")
    parser.add_argument("--no-caption", action="store_true", help="Skip AI caption/description generation")
    parser.add_argument("--caption-model", default=None, help="TokenRouter Anthropic model for caption generation (default: anthropic/claude-haiku-4.5)")
    parser.add_argument("--out", "-o", default=None, help="Exact output image path (overrides --output-dir auto-naming)")
    parser.add_argument("--output-dir", default="tiktok_output", help="Folder to store generated images (default: tiktok_output/)")
    parser.add_argument("--resize", choices=["fit", "pad", "none"], default="fit", help="Resize strategy (default: fit)")
    parser.add_argument("--width", type=int, default=None, help="Target width (default: generator's 1080)")
    parser.add_argument("--height", type=int, default=None, help="Target height (default: generator's 1920)")
    parser.add_argument("--ref", dest="ref", default=None, metavar="PATH_OR_URL", help="Reference image (face/product/logo) to include")
    parser.add_argument("--ref-kind", dest="ref_kind", choices=["preserve", "feature"], default="preserve", help="How the reference appears (default: preserve)")
    parser.add_argument("--retries", type=int, default=2, help="Extra image attempts on a model refusal / no-image response (default: 2)")
    parser.add_argument("--profile", default=None, help="Profile name (profiles/<name>/): uses its persona + reference images")
    parser.add_argument("--profiles-dir", default=None, help="Profiles root folder (default: profiles/)")
    parser.add_argument("--seed", type=int, default=None, help="Seed the random outfit/setting/pose pick (reproducible look); omit for fresh variety")
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
            caption=not args.no_caption,
            caption_model=args.caption_model,
            output=args.out,
            output_dir=args.output_dir,
            resize=args.resize,
            width=args.width,
            height=args.height,
            reference_image=args.ref,
            reference_kind=args.ref_kind,
            image_retries=args.retries,
            profile=args.profile,
            profiles_dir=args.profiles_dir,
            seed=args.seed,
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
    if result.get("caption"):
        print(f"caption:  {result['caption']}")
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
