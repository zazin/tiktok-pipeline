#!/usr/bin/env python3
"""
AI idea generator for TikTok images.

Asks an Anthropic Claude model (served via TokenRouter) to invent ONE concise,
vivid visual idea suitable for a 9:16 TikTok image, which is then fed to
tiktok_image_generator.py. This is what makes the pipeline "fully automatic" —
no human has to think of a prompt.

Like the rest of this project, it talks to TokenRouter's OpenAI-compatible
chat-completions endpoint, so it reuses the SAME credential as image generation:
  - TOKENROUTER_API_KEY

Usage (CLI):
    python idea_generator.py
    python idea_generator.py --theme "cozy coffee shop"
    python idea_generator.py --model anthropic/claude-sonnet-4.6

Usage (as a module):
    from idea_generator import generate_idea
    idea = generate_idea(theme="cyberpunk street food")
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

# Fast & cheap Anthropic model for one-line idea generation. Other options on
# TokenRouter: anthropic/claude-sonnet-4.6, anthropic/claude-opus-4.8, etc.
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

_SYSTEM_PROMPT = (
    "You are a creative director for a viral TikTok image account. "
    "You output a single, concrete, visually striking image idea per request. "
    "The idea must describe one clear scene that an image model can render: "
    "subject, setting, mood, lighting. Keep it to one sentence, under 40 words. "
    "It must work as a vertical 9:16 portrait. "
    "Output ONLY the idea text — no preamble, no quotes, no hashtags, no caption, "
    "no numbering, no explanation."
)

# When a persona/reference image is supplied, the person's identity is fixed by
# a reference photo, so the idea should describe the SCENE around them, not their
# face. This keeps the output usable as an image-to-image transformation prompt.
_PERSONA_SYSTEM_PROMPT = (
    "You are a creative director for a specific person's TikTok account. "
    "Their face and identity are FIXED by a reference photo, so do NOT describe "
    "their facial features, age, or ethnicity. Instead describe ONE concrete "
    "photo scene for them: the setting, their pose, wardrobe/outfit, the mood and "
    "lighting — something on-brand for the persona below. One sentence, under 40 "
    "words, suitable for a vertical 9:16 portrait. "
    "VARY EVERYTHING every time so posts don't look repetitive: "
    "(a) wardrobe — ONE specific outfit with a definite, non-neutral colour or "
    "print; do NOT default to white, cream or beige, and don't repeat the same "
    "garment; "
    "(b) setting — choose a DIFFERENT location (e.g. bathroom mirror, cafe, "
    "bedroom vanity, kitchen, balcony, car, pharmacy aisle, studio backdrop, "
    "outdoors) rather than always a bed; "
    "(c) pose & framing — vary it (standing, walking, mirror selfie, over-the-"
    "shoulder, close-up, mid-laugh, holding a product up) rather than always "
    "sitting cross-legged. "
    "Output ONLY the scene text — no preamble, no quotes, no hashtags, no "
    "explanation."
)


class IdeaError(Exception):
    """Raised when idea generation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise IdeaError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the idea generator."
        )
    return key


def generate_idea(
    theme: Optional[str] = None,
    *,
    persona: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 200,
    timeout: int = 60,
) -> str:
    """
    Generate a single TikTok image idea via an Anthropic model on TokenRouter.

    Args:
        theme: Optional theme to steer the idea (e.g. "cozy coffee",
            "cyberpunk cars"). If None, the model picks something eye-catching.
        persona: Optional persona description. When set (a profile is in use),
            the idea describes a SCENE for that person rather than inventing a
            new subject — the person's identity is fixed by a reference image.
        model: TokenRouter model ID (an Anthropic chat model).
        max_tokens: Response cap (the idea is short, so this is generous).
        timeout: HTTP timeout in seconds.

    Returns:
        A bare one-line image idea string.

    Raises:
        IdeaError: On missing key, API/network error, or empty response.
    """
    has_persona = bool(persona and persona.strip())
    if has_persona:
        system_prompt = _PERSONA_SYSTEM_PROMPT
        parts = [f"Persona: {persona.strip()}"]
        if theme and theme.strip():
            parts.append(f"Theme/occasion to work into the scene: {theme.strip()}.")
        parts.append("Describe one on-brand photo scene for this person.")
        user_msg = " ".join(parts)
    else:
        system_prompt = _SYSTEM_PROMPT
        if theme and theme.strip():
            user_msg = f"Invent one TikTok image idea on the theme: {theme.strip()}."
        else:
            user_msg = (
                "Invent one eye-catching TikTok image idea on any trending, "
                "visually rich theme."
            )

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
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
        raise IdeaError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise IdeaError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise IdeaError(f"Invalid JSON response: {e}") from e

    if "error" in resp:
        raise IdeaError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise IdeaError(f"Unexpected response shape: {e}; body={str(resp)[:300]}")

    # content is usually a string, but may be a list of text parts.
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    idea = (content or "").strip().strip('"').strip()
    if not idea:
        raise IdeaError("Model returned an empty idea.")
    return idea


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Generate a single TikTok image idea via Claude on TokenRouter."
    )
    parser.add_argument(
        "--theme",
        default=None,
        help="Optional theme to steer the idea (e.g. 'cozy coffee shop')",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"TokenRouter Anthropic model ID (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    try:
        idea = generate_idea(theme=args.theme, model=args.model)
    except IdeaError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(idea)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
