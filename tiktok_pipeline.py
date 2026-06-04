#!/usr/bin/env python3
"""
TikTok image pipeline — the top-level "app".

Runs the whole flow end to end:

    1. AI invents a TikTok image idea         (idea_generator.generate_idea)
    2. Write a matching caption + description  (caption_generator.generate_caption)
    3. Generate a 9:16 image from that idea    (tiktok_image_generator.generate_image)
    4. Upload the image to ImageKit CDN        (imagekit_uploader.upload_image)
    5. Store the post record in Airtable       (airtable_logger.create_record)

The pipeline has exactly two outputs: the image lives on ImageKit, and a row in
Airtable describes the post (idea, caption, description, image URL, status). The
downstream tiktok-agent reads that Airtable row to post the content.

The ImageKit upload is non-fatal (recorded in the result). The Airtable log step is
fatal — without the row there is nothing for the agent to post. Pass --prompt to skip
the AI idea step and use your own prompt, or --no-imagekit / --no-airtable to skip a
step.

All generated images are saved into one folder (default: tiktok_output/), so the
whole run history is kept in one place.

Credentials (read from the environment, depending on which steps run):
  - TOKENROUTER_API_KEY   (AI idea step + image generation — both via TokenRouter)
  - IMAGEKIT_PRIVATE_KEY  (ImageKit upload, unless --no-imagekit)
  - IMAGEKIT_PUBLIC_KEY   (ImageKit upload, unless --no-imagekit)
  - AIRTABLE_API_KEY      (Airtable record log, unless --no-airtable)
  - AIRTABLE_BASE_ID      (Airtable record log, unless --no-airtable)
  - AIRTABLE_TABLE_NAME   (Airtable record log, unless --no-airtable)

Usage (CLI):
    # Fully automatic: AI idea -> image -> ImageKit -> Airtable
    python tiktok_pipeline.py

    # Steer the idea by theme
    python tiktok_pipeline.py --theme "cyberpunk street food"

    # Bring your own prompt
    python tiktok_pipeline.py --prompt "neon skyline at dusk"

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
    to_imagekit: bool = True,
    imagekit_folder: str = "/tiktok",
    to_airtable: bool = True,
) -> dict:
    """
    Run the full generate → upload → record pipeline for a single image.

    Returns a result dict:
        {
          "idea": str,
          "path": str,
          "imagekit": {"status": "success"|"failed"|"skipped", "url"/"error": ...},
          "airtable": {"status": "success"|"skipped", "record_id": ...},
        }

    Raises:
        Exception subclasses from the idea/generation steps — those are fatal.
        The Airtable logging step is ALSO fatal: an AirtableError propagates out
        of this function. The ImageKit upload failure is captured in the result
        dict, not raised.
    """
    # Lazy imports so a missing optional dependency or missing creds only break
    # the step that actually needs them.
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
    # Generated up front so it can be logged to the Airtable record alongside
    # the image URL. Non-fatal: a caption failure must not block the image.
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
        "imagekit": {"status": "skipped"},
        "airtable": {"status": "skipped"},
    }

    # --- 3. Upload: ImageKit (non-fatal) ---------------------------------
    # Caption/description are NOT attached as ImageKit custom metadata —
    # they go into the Airtable record below instead.
    if to_imagekit:
        try:
            from imagekit_uploader import upload_image, ImageKitError
            data = upload_image(
                str(path),
                folder=imagekit_folder,
            )
            url = data.get("url", "")
            file_id = data.get("fileId", "")
            result["imagekit"] = {"status": "success", "url": url, "file_id": file_id}
            print(f"ImageKit: {url}")
        except Exception as e:  # ImageKitError or import error
            result["imagekit"] = {"status": "failed", "error": str(e)}
            print(f"ImageKit: FAILED — {e}", file=sys.stderr)

    # --- 4. Log to Airtable (FATAL) --------------------------------------
    # The downstream tiktok-agent reads this record to post the content, so a
    # failure here is fatal: let AirtableError propagate to the caller/CLI.
    if to_airtable:
        from airtable_logger import create_record  # AirtableError is fatal
        ik = result["imagekit"]
        fields = {
            "Idea": idea,
            "Caption": caption_text,
            "Description": description_text,
            "ImageURL": ik.get("url", "") if ik["status"] == "success" else "",
            "ImageKitFileId": ik.get("file_id", "") if ik["status"] == "success" else "",
            "ImagePath": str(path),
            "Profile": profile or "",
            "Status": "pending",
        }
        rec = create_record(fields)
        result["airtable"] = {"status": "success", "record_id": rec["id"]}
        print(f"Airtable: recorded {rec['id']}")

    return result


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Auto-generate a TikTok image, upload it to ImageKit, and record it in Airtable."
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
    # Upload: ImageKit
    parser.add_argument("--no-imagekit", action="store_true", help="Skip uploading to ImageKit")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (default: /tiktok)")
    # Logging: Airtable (the downstream agent's source of truth)
    parser.add_argument("--no-airtable", action="store_true", help="Skip writing the Airtable record")
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
            to_imagekit=not args.no_imagekit,
            imagekit_folder=args.folder,
            to_airtable=not args.no_airtable,
        )
    except Exception as e:
        # Fatal: idea / image-generation / Airtable-logging failure.
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # --- Summary + exit code --------------------------------------------
    ik = result["imagekit"]["status"]
    airtable = result["airtable"]["status"]
    print("\n--- Summary ---")
    print(f"idea:     {result['idea']}")
    if result.get("caption"):
        print(f"caption:  {result['caption']}")
    print(f"image:    {result['path']}")
    print(f"imagekit: {ik}" + (f" ({result['imagekit'].get('url','')})" if ik == "success" else ""))
    print(f"airtable: {airtable}" + (f" ({result['airtable'].get('record_id','')})" if airtable == "success" else ""))

    # Airtable failure is fatal (handled above). Flag a non-zero exit if the
    # ImageKit upload was requested but failed, so the row has no image URL.
    if ik == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
