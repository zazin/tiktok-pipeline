#!/usr/bin/env python3
"""
AI comment generator for TikTok posts.

Given a desired sentiment/intent (e.g. "positive", "negative", "supportive",
"ask a question") and optionally a short note about what the post is about, asks an
Anthropic Claude model (served via TokenRouter) to write ONE natural TikTok comment.

This app does NOT look at the post itself — anything the model should know about the
post is passed in as the ``about`` text. The output is a single comment string,
cleaned to plain ASCII by default because the downstream tiktok-agent types it via
``adb input text`` (which cannot enter emoji / non-ASCII). Reuses TOKENROUTER_API_KEY.

Usage (CLI):
    python comment_generator.py positive
    python comment_generator.py negative --about "a 12-step skincare routine" --json
    python comment_generator.py "ask a friendly question" --about "homemade matcha latte"

    # Reply to a specific comment (used by reply_to_comment.py, not the CLI)
    python -c "from comment_generator import generate_reply; print(generate_reply('friendly', comment_text='makin plenger', comment_author='user210320127'))"

Usage (as a module):
    from comment_generator import generate_comment
    text = generate_comment("positive", about="a jade-green matcha latte on marble")
    print(text)

    from comment_generator import generate_reply
    text = generate_reply("grateful", comment_text="makin plenger", comment_author="user210320127")
    print(text)
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

# Soft upper bound on comment length (characters). The system prompt asks the model
# to stay short; _clean_comment guarantees it for output that ignores the hint.
COMMENT_MAX_CHARS = 150

# Supported comment languages. Indonesian and English are both Latin-script, which
# keeps the comment safely ASCII for the agent's adb typing.
LANGUAGES = ("id", "en")
DEFAULT_LANGUAGE = "id"

_SYSTEM_PROMPT = (
    "You are a real person leaving ONE short comment on a TikTok video. "
    "Given the desired sentiment/intent (and, when provided, a short note about "
    "what the video is about), write a single natural-sounding comment.\n"
    "Rules:\n"
    "- Respond with ONLY the comment text — no quotes, no JSON, no markdown, no "
    "hashtags, no emojis, and no surrounding explanation.\n"
    "- Keep it to one line, casual and human, under ~120 characters.\n"
    "- Use ONLY plain ASCII characters (no emoji, no accented letters): the comment "
    "is typed by a device that cannot enter non-ASCII characters.\n"
    "- Match the requested sentiment. If it is negative/critical, keep it as a "
    "blunt opinion, not harassment, slurs, or threats."
)


def _language_clause(language: str) -> str:
    """Return the per-call instruction picking the comment language."""
    if language == "en":
        return "\nWrite the comment in ENGLISH."
    # default "id"
    return "\nWrite the comment in Indonesian (Bahasa Indonesia), natural and casual."


# A second system prompt tailored for REPLIES — the model is shown both the comment
# being replied to (author + text) and an optional post context, and asked to write
# a short reply that addresses that specific comment. The rules are the same
# (ASCII, no emoji, no hashtags, one line) but the "respond to this specific
# comment" framing is essential — otherwise the model drifts into top-level
# comments about the post and ignores the input.
_REPLY_SYSTEM_PROMPT = (
    "You are a real person leaving ONE short REPLY to an existing comment on a "
    "TikTok video. You are given the comment's author handle and text, plus an "
    "optional short note about what the video is about for context.\n"
    "Rules:\n"
    "- Respond with ONLY the reply text — no quotes, no JSON, no markdown, no "
    "hashtags, no emojis, and no surrounding explanation.\n"
    "- Address the COMMENT you are replying to (react to what they actually said), "
    "not the video itself. Keep it conversational — it should feel like a real "
    "person responding in a thread, not a fresh standalone comment.\n"
    "- Keep it to one line, casual and human, under ~120 characters.\n"
    "- Use ONLY plain ASCII characters (no emoji, no accented letters): the reply "
    "is typed by a device that cannot enter non-ASCII characters.\n"
    "- Match the requested sentiment. If it is negative/critical, keep it as a "
    "blunt opinion, not harassment, slurs, or threats."
)


class CommentGenError(Exception):
    """Raised when comment generation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise CommentGenError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the comment generator."
        )
    return key


def generate_comment(
    sentiment: str,
    *,
    about: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    ascii_only: bool = True,
    max_tokens: int = 120,
    timeout: int = 60,
) -> str:
    """
    Generate one TikTok comment from a desired sentiment/intent.

    Args:
        sentiment: The desired tone/intent of the comment, e.g. "positive",
            "negative", "supportive", "ask a question".
        about: Optional short note about what the post is about, so the comment is
            relevant. This app never fetches the post itself; supply context here.
        language: Comment language — "id" (Indonesian, default) or "en" (English).
        model: TokenRouter model ID (an Anthropic chat model).
        ascii_only: Strip non-ASCII from the result (default True) so it survives the
            agent's ``adb input text`` typing unchanged.
        max_tokens: Response cap.
        timeout: HTTP timeout in seconds.

    Returns:
        The comment string.

    Raises:
        CommentGenError: On empty sentiment, missing key, API/network error, or an
            empty result.
    """
    if not sentiment or not sentiment.strip():
        raise CommentGenError("Sentiment must not be empty.")
    if language not in LANGUAGES:
        raise CommentGenError(f"Unsupported language {language!r}; choose one of {LANGUAGES}.")

    parts = [f"Desired sentiment/intent: {sentiment.strip()}"]
    if about and about.strip():
        parts.append(f"What the video is about: {about.strip()}")
    user_msg = "\n".join(parts)

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT + _language_clause(language)},
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
        raise CommentGenError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise CommentGenError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise CommentGenError(f"Invalid JSON response: {e}") from e

    if "error" in resp:
        raise CommentGenError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise CommentGenError(f"Unexpected response shape: {e}; body={str(resp)[:300]}")

    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    comment = _clean_comment(content or "", ascii_only=ascii_only)
    if not comment:
        raise CommentGenError("Model returned an empty comment after cleaning.")
    return comment


def generate_reply(
    sentiment: str,
    *,
    comment_text: str,
    comment_author: str,
    about: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    ascii_only: bool = True,
    max_tokens: int = 120,
    timeout: int = 60,
) -> str:
    """
    Generate one TikTok REPLY to an existing comment on a post.

    Unlike ``generate_comment`` (which writes a top-level comment from a sentiment +
    optional post context), this is given a specific comment to react to — author
    handle and text — and produces a short reply that addresses that comment. Used
    by ``reply_to_comment.reply_to_comments`` for the read-then-reply loop.

    The output is the reply text. The caller is responsible for placing it on the
    right post via ``hivemq_publisher.publish_comment(post_url, reply, reply_to={...})``,
    where ``reply_to`` carries the same ``{author, text?}`` the model was given.

    Args:
        sentiment: The desired tone/intent of the reply, e.g. ``"friendly"``,
            ``"grateful"``, ``"supportive"``, ``"answer a question"``, ``"witty"``.
        comment_text: The text of the comment being replied to. Must be non-empty.
        comment_author: The author handle of the comment being replied to
            (without the leading ``@``). Must be non-empty — used as the model
            input AND later echoed back in ``ReplyTo.author`` for the agent to
            find the comment in the sheet.
        about: Optional short note about what the post is about, so the reply
            has video context if the comment doesn't make it self-evident.
        language: Reply language — ``"id"`` (Indonesian, default) or ``"en"``.
        model: TokenRouter model ID.
        ascii_only: Strip non-ASCII from the result (default True) so it
            survives the agent's ``adb input text`` typing.
        max_tokens: Response cap.
        timeout: HTTP timeout in seconds.

    Returns:
        The reply string.

    Raises:
        CommentGenError: On empty sentiment/comment_text/comment_author, missing
            key, API/network error, or an empty result.
    """
    if not sentiment or not sentiment.strip():
        raise CommentGenError("Sentiment must not be empty.")
    if not comment_text or not comment_text.strip():
        raise CommentGenError("comment_text must not be empty (nothing to reply to).")
    if not comment_author or not comment_author.strip():
        raise CommentGenError("comment_author must not be empty (used to target the reply).")
    if language not in LANGUAGES:
        raise CommentGenError(f"Unsupported language {language!r}; choose one of {LANGUAGES}.")

    # Strip the leading @ if the caller passed it (the model doesn't need it;
    # the agent's ReplyTo.author also tolerates a leading @, so being lenient
    # on the way in keeps the data flow simple).
    author_handle = comment_author.strip().lstrip("@")
    if not author_handle:
        raise CommentGenError("comment_author must contain non-@ characters.")

    parts = [
        f"Desired sentiment/intent for the reply: {sentiment.strip()}",
        f"Comment author: @{author_handle}",
        f"Comment text: {comment_text.strip()}",
    ]
    if about and about.strip():
        parts.append(f"Video context (for grounding, do NOT comment on the video directly): {about.strip()}")
    user_msg = "\n".join(parts)

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": _REPLY_SYSTEM_PROMPT + _language_clause(language)},
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
        raise CommentGenError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise CommentGenError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise CommentGenError(f"Invalid JSON response: {e}") from e

    if "error" in resp:
        raise CommentGenError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise CommentGenError(f"Unexpected response shape: {e}; body={str(resp)[:300]}")

    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    reply = _clean_comment(content or "", ascii_only=ascii_only)
    if not reply:
        raise CommentGenError("Model returned an empty reply after cleaning.")
    return reply


def _clean_comment(text: str, *, ascii_only: bool = True, limit: int = COMMENT_MAX_CHARS) -> str:
    """Strip fences/quotes, collapse whitespace, optionally force ASCII, and trim."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
    # Collapse any newlines / runs of whitespace into single spaces.
    s = " ".join(s.split())
    # Drop a single pair of wrapping quotes the model sometimes adds.
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1].strip()
    if ascii_only:
        s = s.encode("ascii", "ignore").decode("ascii")
        s = " ".join(s.split())
    if len(s) > limit:
        clipped = s[:limit].rstrip()
        spaced = clipped.rsplit(" ", 1)[0] if " " in clipped else clipped
        if len(spaced) >= limit * 0.6:
            clipped = spaced
        s = clipped.rstrip()
    return s


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Generate one TikTok comment from a desired sentiment/intent."
    )
    parser.add_argument("sentiment", help='Desired tone/intent, e.g. "positive", "negative", "ask a question"')
    parser.add_argument("--about", default=None, help="Short note about what the post is about (for relevance)")
    parser.add_argument("--language", "--lang", dest="language", choices=list(LANGUAGES), default=DEFAULT_LANGUAGE, help=f"Comment language: id (default) or en (default: {DEFAULT_LANGUAGE})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument("--keep-non-ascii", action="store_true", help="Do NOT strip non-ASCII (the agent will strip it anyway when typing)")
    args = parser.parse_args()

    try:
        comment = generate_comment(
            args.sentiment,
            about=args.about,
            language=args.language,
            model=args.model,
            ascii_only=not args.keep_non_ascii,
        )
    except CommentGenError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(comment)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
