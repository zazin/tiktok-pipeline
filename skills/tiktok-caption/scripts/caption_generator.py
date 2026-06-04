#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
AI caption generator for TikTok posts.

Given an image concept (the idea/theme that drives image generation), asks an
Anthropic Claude model (served via TokenRouter) for the *post text*: a catchy
caption plus a short description. This is a separate, text-only call — it does
NOT generate an image — and is meant to run BEFORE image creation so the caption
can be attached to the uploaded image as ImageKit custom metadata.

Like the rest of this project it reuses TOKENROUTER_API_KEY.

Usage (CLI):
    python caption_generator.py "a jade-green matcha latte on white marble"
    python caption_generator.py "neon ramen cart" --json

Usage (as a module):
    from caption_generator import generate_caption
    cap = generate_caption("a jade-green matcha latte on white marble")
    print(cap["caption"], cap["description"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional


TOKENROUTER_BASE_URL = "https://api.tokenrouter.com/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

_SYSTEM_PROMPT = (
    "You are a TikTok content writer. Given an image concept, write the post "
    "text for it. Respond with ONLY a JSON object, no markdown fences, no extra "
    "text, with exactly these keys:\n"
    '  "caption": a single scroll-stopping line for the TikTok post — include '
    "1-3 fitting emojis and 3-5 relevant hashtags. Keep it under ~150 chars.\n"
    '  "description": one or two plain sentences describing the post for context '
    "(no hashtags, no emojis).\n"
    "Match the language to the concept; default to English."
)


class CaptionError(Exception):
    """Raised when caption generation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise CaptionError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the caption generator."
        )
    return key


def generate_caption(
    subject: str,
    *,
    persona: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 400,
    timeout: int = 60,
) -> dict:
    """
    Generate a TikTok caption + description for an image concept.

    Args:
        subject: The image concept/idea/theme the post is about.
        persona: Optional persona description; when set, the caption is written
            in that person's voice/niche (a profile is in use).
        model: TokenRouter model ID (an Anthropic chat model).
        max_tokens: Response cap.
        timeout: HTTP timeout in seconds.

    Returns:
        {"caption": str, "description": str}.

    Raises:
        CaptionError: On missing key, API/network error, or unparseable output.
    """
    if not subject or not subject.strip():
        raise CaptionError("Subject must not be empty.")

    if persona and persona.strip():
        user_msg = (
            f"Persona (write in their voice): {persona.strip()}\n"
            f"Image concept: {subject.strip()}"
        )
    else:
        user_msg = f"Image concept: {subject.strip()}"

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    }
    body = json.dumps(payload).encode()

    req = urllib.request.Request(
        f"{TOKENROUTER_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise CaptionError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise CaptionError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise CaptionError(f"Invalid JSON response: {e}") from e

    if "error" in resp:
        raise CaptionError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise CaptionError(f"Unexpected response shape: {e}; body={str(resp)[:300]}")

    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    return _parse_caption(content or "")


def _parse_caption(text: str) -> dict:
    """Extract the JSON object from the model's reply, tolerating stray prose/fences."""
    s = text.strip()
    # Strip ```json fences if present.
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    # Grab the outermost {...} span.
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise CaptionError(f"Could not parse caption JSON from model output: {e}; got {text[:200]!r}")

    caption = str(data.get("caption", "")).strip()
    description = str(data.get("description", "")).strip()
    if not caption:
        raise CaptionError("Model returned an empty caption.")
    return {"caption": caption, "description": description}


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Generate a TikTok caption + description for an image concept."
    )
    parser.add_argument("subject", help="The image concept/idea the post is about")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Print the full JSON object")
    args = parser.parse_args()

    try:
        cap = generate_caption(args.subject, model=args.model)
    except CaptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(cap, indent=2, ensure_ascii=False))
    else:
        print(f"Caption:     {cap['caption']}")
        print(f"Description: {cap['description']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
