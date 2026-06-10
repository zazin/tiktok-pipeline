#!/usr/bin/env python3
"""
TikTok image pipeline — the top-level "app".

Runs the whole flow end to end:

    1. AI invents a TikTok image idea         (idea_generator.generate_idea)
    2. Write a matching caption + description  (content_generator.generate_content)
    3. Generate a 9:16 image from that idea    (tiktok_image_generator.generate_image)
    4. Upload the image to ImageKit CDN        (imagekit_uploader.upload_image)
    5. Push the post to HiveMQ                  (hivemq_publisher.publish_post)

The pipeline's outputs are: the image lives on ImageKit, and a HiveMQ message
describes the post (idea, caption, description, image URL, status). The downstream
tiktok-agent subscribes to that HiveMQ topic and posts the content.

The ImageKit upload is non-fatal (recorded in the result). The HiveMQ publish is
also non-fatal (recorded in the result). Pass --prompt to skip the AI idea step and
use your own prompt, or --no-imagekit / --no-hivemq to skip a step.

All generated images are saved into one folder (default: tiktok_output/), so the
whole run history is kept in one place.

Credentials (read from the environment, depending on which steps run):
  - TOKENROUTER_API_KEY   (AI idea step + image generation — both via TokenRouter)
  - IMAGEKIT_PRIVATE_KEY  (ImageKit upload, unless --no-imagekit)
  - IMAGEKIT_PUBLIC_KEY   (ImageKit upload, unless --no-imagekit)
  - HIVEMQ_HOST           (HiveMQ push, unless --no-hivemq)
  - HIVEMQ_USERNAME       (HiveMQ push, unless --no-hivemq)
  - HIVEMQ_PASSWORD       (HiveMQ push, unless --no-hivemq)
  - TIKTOK_ACCOUNT        (optional) TikTok @handle (e.g. "@captgani") to add
                          to the published post as the "Account" field. The
                          downstream tiktok-agent switches to it before posting;
                          if the account is not active it reports "wrong_account"
                          and does not post. Omit / empty = post as the currently
                          active account. Pass --account to override.
  - TIKTOK_ACCOUNT_<PROFILE> (optional) per-profile default, e.g.
                          TIKTOK_ACCOUNT_GANI=@captgani,
                          TIKTOK_ACCOUNT_KALILA=@likaliku.skin. When the
                          pipeline runs with --profile <name>, the matching
                          TIKTOK_ACCOUNT_<UPPER(name)> wins over the generic
                          TIKTOK_ACCOUNT. --account always wins over both.

Usage (CLI):
    # Fully automatic: AI idea -> image -> ImageKit -> HiveMQ
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
    language: str = "id",
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
    to_hivemq: bool = True,
    account: Optional[str] = None,
) -> dict:
    """
    Run the full generate → upload → publish pipeline for a single image.

    Returns a result dict:
        {
          "idea": str,
          "path": str,
          "imagekit": {"status": "success"|"failed"|"skipped", "url"/"error": ...},
          "hivemq": {"status": "success"|"failed"|"skipped", "topic"/"error": ...},
        }

    Raises:
        Exception subclasses from the idea/generation steps — those are fatal.
        The ImageKit upload and HiveMQ publish failures are captured in the result
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
    # Generated up front so it can be included in the HiveMQ message alongside
    # the image URL. Non-fatal: a caption failure must not block the image.
    caption_text = ""
    description_text = ""
    if caption:
        try:
            from content_generator import generate_content, DEFAULT_MODEL as CAP_MODEL
            cap = generate_content(idea, persona=persona, language=language, model=caption_model or CAP_MODEL)
            caption_text = cap.get("caption", "")
            description_text = cap.get("description", "")
            print(f"Caption: {caption_text}")
        except Exception as e:  # ContentError or import error
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
        "hivemq": {"status": "skipped"},
    }

    # --- 3. Upload: ImageKit (non-fatal) ---------------------------------
    # Caption/description are NOT attached as ImageKit custom metadata —
    # they go into the HiveMQ message below instead.
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

    # --- 4. Push to HiveMQ (non-fatal) -----------------------------------
    # The downstream tiktok-agent subscribes to the HiveMQ topic and posts the
    # content. Non-fatal: a broker hiccup is recorded in the result, not raised.
    if to_hivemq:
        try:
            from hivemq_publisher import publish_post, resolve_account
            ik = result["imagekit"]
            # Resolve Account: --account > TIKTOK_ACCOUNT_<UPPER(profile)>
            # (when a profile is active) > generic TIKTOK_ACCOUNT > omit.
            # resolve_account() returns "" for "nothing set"; we never send
            # "Account": "" (the agent contract treats empty and missing the
            # same, so omitting is cleaner).
            resolved_account = resolve_account(explicit=account, profile=profile)
            payload = {
                "Idea": idea,
                "Caption": caption_text,
                "Description": description_text,
                "ImageURL": ik.get("url", "") if ik["status"] == "success" else "",
                "ImageKitFileId": ik.get("file_id", "") if ik["status"] == "success" else "",
                "ImagePath": path.name,  # filename + ext only, e.g. tiktok_20260604_230055.jpeg
                "Profile": profile or "",
                "Account": resolved_account or "",
                "Status": "pending",
            }
            pub = publish_post(payload)
            result["hivemq"] = {"status": "success", "topic": pub["topic"]}
            print(f"HiveMQ: published to {pub['topic']}")
        except Exception as e:  # HiveMQError or import error — non-fatal
            result["hivemq"] = {"status": "failed", "error": str(e)}
            print(f"HiveMQ: FAILED — {e}", file=sys.stderr)

    return result


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Auto-generate a TikTok image, upload it to ImageKit, and push the post to HiveMQ."
    )
    # Idea / generation
    parser.add_argument("--prompt", default=None, help="Use this exact prompt instead of an AI-generated idea")
    parser.add_argument("--theme", default=None, help="Theme to steer the AI idea (ignored if --prompt is set)")
    parser.add_argument("--model", default=None, help="TokenRouter image model ID (default: generator's default)")
    parser.add_argument("--idea-model", default=None, help="TokenRouter Anthropic model for idea generation (default: anthropic/claude-haiku-4.5)")
    parser.add_argument("--no-caption", action="store_true", help="Skip AI caption/description generation")
    parser.add_argument("--caption-model", default=None, help="TokenRouter Anthropic model for caption generation (default: anthropic/claude-haiku-4.5)")
    parser.add_argument("--language", "--lang", dest="language", choices=["id", "en"], default="id", help="Post-copy language: id (default) or en")
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
    parser.add_argument("--account", default=None, help="TikTok @handle (e.g. @captgani) — agent switches account before posting. Default: TIKTOK_ACCOUNT env var, else omitted.")
    # Upload: ImageKit
    parser.add_argument("--no-imagekit", action="store_true", help="Skip uploading to ImageKit")
    parser.add_argument("--folder", default="/tiktok", help="ImageKit folder (default: /tiktok)")
    # Push: HiveMQ (the downstream agent's source of truth)
    parser.add_argument("--no-hivemq", action="store_true", help="Skip publishing the post to HiveMQ")
    args = parser.parse_args()

    try:
        result = run_pipeline(
            prompt=args.prompt,
            theme=args.theme,
            model=args.model,
            idea_model=args.idea_model,
            caption=not args.no_caption,
            caption_model=args.caption_model,
            language=args.language,
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
            to_hivemq=not args.no_hivemq,
            account=args.account,
        )
    except Exception as e:
        # Fatal: idea / image-generation failure.
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # --- Summary + exit code --------------------------------------------
    ik = result["imagekit"]["status"]
    hivemq = result["hivemq"]["status"]
    print("\n--- Summary ---")
    print(f"idea:     {result['idea']}")
    if result.get("caption"):
        print(f"caption:  {result['caption']}")
    print(f"image:    {result['path']}")
    print(f"imagekit: {ik}" + (f" ({result['imagekit'].get('url','')})" if ik == "success" else ""))
    print(f"hivemq:   {hivemq}" + (f" ({result['hivemq'].get('topic','')})" if hivemq == "success" else ""))

    # Flag a non-zero exit if the ImageKit upload was requested but failed (the
    # HiveMQ message would carry no image URL), or if the HiveMQ publish failed.
    if ik == "failed" or hivemq == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
