#!/usr/bin/env python3
"""
AI content generator for TikTok posts.

Given a topic/idea, asks an Anthropic Claude model (served via TokenRouter) for
the full text package for one post, in a single call:
  - image_prompt — a vivid one-line prompt to feed an image model (tiktok-image)
  - caption      — a scroll-stopping line for the post (with emojis)
  - description  — one or two plain sentences of context
  - hashtags     — a list of relevant hashtags

This is a text-only call — it does NOT generate an image. Reuses TOKENROUTER_API_KEY.

Usage (CLI):
    python content_generator.py "a jade-green matcha latte on white marble"
    python content_generator.py "morning skincare routine" --persona "Lika, ..." --json

Usage (as a module):
    from content_generator import generate_content
    c = generate_content("a jade-green matcha latte on white marble")
    print(c["image_prompt"], c["caption"], c["description"], c["hashtags"])
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

# Hard upper bound on caption length (characters, incl. emojis/spaces). The
# system prompt asks the model to stay under this, and _enforce_caption_limit
# guarantees it for any model output that ignores the instruction.
CAPTION_MAX_CHARS = 90

_SYSTEM_PROMPT = (
    "You are a TikTok content creator. Given a topic/idea, produce the complete "
    "text package for ONE vertical 9:16 image post. Respond with ONLY a JSON "
    "object — no markdown fences, no extra text — with exactly these keys:\n"
    '  "image_prompt": one vivid, concrete prompt for an image model describing a '
    "single 9:16 scene — subject, setting, mood, lighting. Under ~50 words. Just "
    "describe the scene, no camera jargon.\n"
    '  "caption": one scroll-stopping line for the post with 1-3 fitting emojis '
    "and NO hashtags. MUST be at most 90 characters, including emojis and spaces.\n"
    '  "description": one or two plain sentences of context (no hashtags, no '
    "emojis).\n"
    '  "hashtags": an array of 3-7 relevant hashtag strings, each starting with '
    '"#", no spaces.\n'
    "Match the language to the topic; default to English."
)

# When a persona is supplied, identity is fixed by a reference photo at image
# time, so the image_prompt should describe the SCENE around the person (not
# their face), and the caption should be in that person's voice.
_PERSONA_NOTE = (
    "The post is for a specific recurring person whose face/identity is FIXED by "
    "a reference photo. Do NOT describe their facial features, age, or ethnicity "
    "in image_prompt — describe the scene, pose, wardrobe, mood and lighting. "
    "Write the caption in this person's voice/niche."
)


class ContentError(Exception):
    """Raised when content generation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise ContentError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the content generator."
        )
    return key


def generate_content(
    topic: str,
    *,
    persona: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 600,
    timeout: int = 60,
) -> dict:
    """
    Generate the full text package for a TikTok post from a topic/idea.

    Args:
        topic: The topic/idea/concept the post is about.
        persona: Optional persona description; when set, the caption is written in
            that person's voice and the image_prompt describes the scene (not the
            face, whose identity is fixed by a reference image).
        model: TokenRouter model ID (an Anthropic chat model).
        max_tokens: Response cap.
        timeout: HTTP timeout in seconds.

    Returns:
        {"image_prompt": str, "caption": str, "description": str,
         "hashtags": list[str]}.

    Raises:
        ContentError: On missing key, API/network error, or unparseable output.
    """
    if not topic or not topic.strip():
        raise ContentError("Topic must not be empty.")

    parts = []
    if persona and persona.strip():
        parts.append(_PERSONA_NOTE)
        parts.append(f"Persona: {persona.strip()}")
    parts.append(f"Topic/idea: {topic.strip()}")
    user_msg = "\n".join(parts)

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
        raise ContentError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise ContentError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise ContentError(f"Invalid JSON response: {e}") from e

    if "error" in resp:
        raise ContentError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ContentError(f"Unexpected response shape: {e}; body={str(resp)[:300]}")

    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    return _parse_content(content or "")


def _normalize_hashtags(value) -> list[str]:
    """Coerce the model's hashtags into a clean list of '#tag' strings."""
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = []
    tags = []
    for raw in items:
        tag = raw.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        tags.append(tag)
    return tags


def _enforce_caption_limit(caption: str, limit: int = CAPTION_MAX_CHARS) -> str:
    """Trim a caption to at most ``limit`` characters, preferring a word boundary."""
    if len(caption) <= limit:
        return caption
    clipped = caption[:limit].rstrip()
    spaced = clipped.rsplit(" ", 1)[0] if " " in clipped else clipped
    # Only keep the word-boundary cut if it doesn't lose too much of the caption.
    if len(spaced) >= limit * 0.6:
        clipped = spaced
    return clipped.rstrip()


def _parse_content(text: str) -> dict:
    """Extract the JSON object from the model's reply, tolerating stray prose/fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise ContentError(f"Could not parse content JSON from model output: {e}; got {text[:200]!r}")

    image_prompt = str(data.get("image_prompt", "")).strip()
    caption = _enforce_caption_limit(str(data.get("caption", "")).strip())
    description = str(data.get("description", "")).strip()
    hashtags = _normalize_hashtags(data.get("hashtags"))
    if not image_prompt:
        raise ContentError("Model returned an empty image_prompt.")
    if not caption:
        raise ContentError("Model returned an empty caption.")
    return {
        "image_prompt": image_prompt,
        "caption": caption,
        "description": description,
        "hashtags": hashtags,
    }


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Generate a TikTok post's image prompt + caption + description + hashtags from a topic."
    )
    parser.add_argument("topic", help="The topic/idea the post is about")
    parser.add_argument("--persona", default=None, help="Persona description; writes the caption in their voice and keeps the image prompt scene-focused")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Print the full JSON object")
    args = parser.parse_args()

    try:
        c = generate_content(args.topic, persona=args.persona, model=args.model)
    except ContentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(c, indent=2, ensure_ascii=False))
    else:
        print(f"Image prompt: {c['image_prompt']}")
        print(f"Caption:      {c['caption']}")
        print(f"Description:  {c['description']}")
        print(f"Hashtags:     {' '.join(c['hashtags'])}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
