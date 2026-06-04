#!/usr/bin/env python3
"""
Profiles — a reusable persona + reference images for the pipeline.

A profile is a folder under `profiles/<name>/` containing reference photos of a
person plus a `profile.json`:

    profiles/kalila/
      profile.json
      make_a_portrait_of_her_...jpeg
      make_a_full_body_image_...jpeg

profile.json schema:
    {
      "name": "Kalila",
      "persona": "free-text description of who they are / vibe / niche / tone",
      "reference_images": ["portrait.jpeg", "full_body.jpeg"],
      "reference_kind": "preserve"
    }

When the pipeline runs with --profile <name>, the reference images preserve the
person's identity in every generated image, and the persona steers the AI idea
and caption.

Usage (CLI):
    python profile_loader.py --list
    python profile_loader.py kalila

Usage (as a module):
    from profile_loader import load_profile
    p = load_profile("kalila")
    p["reference_paths"]  # absolute paths to the reference images
    p["persona"]          # persona text
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


DEFAULT_PROFILES_DIR = "profiles"
PROFILE_CONFIG = "profile.json"


class ProfileError(Exception):
    """Raised when a profile can't be loaded."""


def _profiles_root(profiles_dir: Optional[str]) -> Path:
    # Resolve relative to this module so it works regardless of CWD.
    base = Path(profiles_dir or DEFAULT_PROFILES_DIR)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent / base
    return base


def list_profiles(profiles_dir: Optional[str] = None) -> list[str]:
    """Return the names of profiles that have a profile.json."""
    root = _profiles_root(profiles_dir)
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / PROFILE_CONFIG).is_file()
    )


def load_profile(name: str, *, profiles_dir: Optional[str] = None) -> dict:
    """
    Load a profile by name.

    Returns:
        {
          "name": str,
          "persona": str,
          "reference_paths": list[str],   # absolute paths, verified to exist
          "reference_kind": "preserve" | "feature",
          "dir": str,
        }

    Raises:
        ProfileError: If the profile, its config, or its reference images are missing.
    """
    root = _profiles_root(profiles_dir)
    pdir = root / name
    if not pdir.is_dir():
        available = ", ".join(list_profiles(profiles_dir)) or "(none)"
        raise ProfileError(f"Profile {name!r} not found in {root}. Available: {available}")

    cfg_path = pdir / PROFILE_CONFIG
    if not cfg_path.is_file():
        raise ProfileError(f"Profile {name!r} has no {PROFILE_CONFIG} in {pdir}")

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProfileError(f"Invalid {PROFILE_CONFIG} for {name!r}: {e}") from e

    refs = cfg.get("reference_images") or []
    if not refs:
        raise ProfileError(f"Profile {name!r} lists no reference_images in {PROFILE_CONFIG}")

    reference_paths: list[str] = []
    for ref in refs:
        rp = (pdir / ref).resolve()
        if not rp.is_file():
            raise ProfileError(f"Profile {name!r} reference image not found: {rp}")
        reference_paths.append(str(rp))

    kind = cfg.get("reference_kind", "preserve")
    if kind not in ("preserve", "feature"):
        raise ProfileError(f"Profile {name!r}: reference_kind must be 'preserve' or 'feature', got {kind!r}")

    variety = cfg.get("variety")
    if variety is not None and not isinstance(variety, dict):
        raise ProfileError(f"Profile {name!r}: 'variety' must be an object of pools, got {type(variety).__name__}")

    return {
        "name": cfg.get("name", name),
        "persona": _build_persona(cfg),
        "reference_paths": reference_paths,
        "reference_kind": kind,
        "variety": variety,
        "dir": str(pdir),
    }


def _build_persona(cfg: dict) -> str:
    """
    Compose the effective persona string passed to the AI from the config:
    the base persona, plus a one-line demographic header and the content
    pillars (so generated scenes stay on-brand).
    """
    parts: list[str] = []

    demo = ", ".join(
        str(cfg[k]) for k in ("gender", "generation", "age", "industry") if cfg.get(k)
    )
    if demo:
        parts.append(f"{cfg.get('name', 'The creator')} — {demo}.")

    persona = (cfg.get("persona") or "").strip()
    if persona:
        parts.append(persona)

    pillars = cfg.get("content_pillars") or []
    if isinstance(pillars, list) and pillars:
        parts.append("Recurring content pillars: " + " | ".join(str(p) for p in pillars))

    return " ".join(parts).strip()


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Inspect pipeline profiles.")
    parser.add_argument("name", nargs="?", help="Profile to show (omit with --list)")
    parser.add_argument("--list", action="store_true", help="List available profiles")
    parser.add_argument("--profiles-dir", default=None, help=f"Profiles root (default: {DEFAULT_PROFILES_DIR}/)")
    args = parser.parse_args()

    if args.list or not args.name:
        names = list_profiles(args.profiles_dir)
        print("Profiles:" if names else "No profiles found.")
        for n in names:
            print(f"  {n}")
        return 0

    try:
        p = load_profile(args.name, profiles_dir=args.profiles_dir)
    except ProfileError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"name:           {p['name']}")
    print(f"reference_kind: {p['reference_kind']}")
    print(f"persona:        {p['persona']}")
    print("reference_paths:")
    for rp in p["reference_paths"]:
        print(f"  {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
