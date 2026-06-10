#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["paho-mqtt>=2.0"]
# ///
"""
Comment on an existing TikTok post.

Ties the two tools this repo provides for commenting:
  1. comment_generator.generate_comment — AI-write a comment from a sentiment/intent
     (skipped when you pass an exact --comment to publish verbatim)
  2. hivemq_publisher.publish_comment    — publish one {PostURL, Comment} message to
     the "tiktok/comments" topic; the downstream tiktok-agent opens the post by URL
     and leaves the comment (see tiktok-agent docs/comment-on-post.md).

This app never looks at the post itself — give the generator context with --about.

Credentials are read from the environment (or a local .env):
  - TOKENROUTER_API_KEY                               (AI comment generation)
  - HIVEMQ_HOST / HIVEMQ_USERNAME / HIVEMQ_PASSWORD   (HiveMQ publish)

Usage (CLI):
    # AI-generate a positive comment and publish it
    python comment_on_post.py https://www.tiktok.com/@user/video/123 --sentiment positive

    # give the AI context about the post for a more relevant comment
    python comment_on_post.py <url> --sentiment negative --about "a 12-step skincare routine"

    # publish an exact comment verbatim (no AI)
    python comment_on_post.py <url> --comment "Nice video!"

    # reply to a specific existing comment (one-off, no read loop)
    python comment_on_post.py <url> --comment "Makasih kak!" --reply-to-author user210320127 --reply-to-text "makin plenger"

    # leave the comment as a specific TikTok account (else uses TIKTOK_ACCOUNT env var)
    python comment_on_post.py <url> --comment "Welcome to the channel!" --account @captgani

Usage (as a module):
    from comment_on_post import comment_on_post
    result = comment_on_post("https://.../video/123", sentiment="positive")
    print(result["comment"], result["hivemq"]["topic"])

    # Reply to a specific comment
    result = comment_on_post(
        "https://.../video/123",
        comment="Makasih kak!",
        reply_to={"author": "user210320127", "text": "makin plenger"},
    )
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


# Defaults mirrored from comment_generator so callers/CLI don't have to import it.
DEFAULT_LANGUAGE = "id"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

# Public, no-auth TikTok oEmbed endpoint — returns {title, author_name, ...} for any
# public post. We use the title (which already includes hashtags) as the AI context
# when the caller didn't pass --about. Private / region-locked posts return non-200
# and the fetch degrades silently with a stderr warning.
OEMBED_URL = "https://www.tiktok.com/oembed"
OEMBED_TIMEOUT = 10


class CommentError(Exception):
    """Raised when the comment-on-post step fails."""


def _fetch_post_context(post_url: str) -> Optional[str]:
    """
    Fetch post context from TikTok's public oEmbed endpoint.

    Returns the post title (which already includes the caption + hashtags) as a
    cleaned single-line string, or ``None`` if the fetch fails for any reason
    (private post, region-locked, network error, unexpected shape). The caller
    is expected to fall back to a no-context comment in that case.

    Args:
        post_url: The full TikTok post URL.

    Returns:
        The cleaned title string, or None on failure.
    """
    try:
        qs = urllib.parse.urlencode({"url": post_url})
        req = urllib.request.Request(
            f"{OEMBED_URL}?{qs}",
            headers={"User-Agent": "tiktok-comment/1.0 (+oembed-context)"},
        )
        with urllib.request.urlopen(req, timeout=OEMBED_TIMEOUT) as r:
            data = json.loads(r.read())
        title = (data.get("title") or "").strip()
        # Collapse runs of whitespace (the oEmbed title has them around hashtags).
        title = " ".join(title.split())
        return title or None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(
            f"Warning: oEmbed auto-context failed ({e.__class__.__name__}); "
            f"proceeding without post context.",
            file=sys.stderr,
        )
        return None


def comment_on_post(
    post_url: str,
    *,
    sentiment: Optional[str] = None,
    comment: Optional[str] = None,
    about: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    ascii_only: bool = True,
    topic: Optional[str] = None,
    auto_context: bool = True,
    account: Optional[str] = None,
    reply_to: Optional[dict] = None,
) -> dict:
    """
    Generate (or accept) a comment and publish it for an existing TikTok post.

    Provide EITHER ``comment`` (published verbatim) OR ``sentiment`` (the AI writes
    the comment from that intent). ``about`` gives the AI context about the post.

    Two optional fields are forwarded to the publish:

    - ``account`` — TikTok @handle. Resolved via the same chain as the post
      publisher (explicit > ``TIKTOK_ACCOUNT`` env var > omitted). The agent
      switches to that account before opening the post; if it can't, it reports
      ``wrong_account`` and does not comment.
    - ``reply_to`` — dict ``{"author": <@handle>, "text"?: <substring>}`` to
      submit the comment as a *reply to* an existing top-level comment. Requires
      ``reply_to["author"]`` to be non-empty; ``text`` is optional and only
      disambiguates when the same author has multiple comments on the post.

    Args:
        post_url: Full TikTok post URL to comment on.
        sentiment: Desired tone/intent for AI generation (e.g. "positive").
        comment: Exact comment text; when set, AI generation is skipped.
        about: Short note about what the post is about (improves AI relevance).
        language: AI comment language — "id" (default) or "en".
        model: TokenRouter model for AI generation.
        ascii_only: Strip non-ASCII so the comment survives the agent's adb typing.
        topic: Override HIVEMQ_COMMENT_TOPIC.
        auto_context: When True and ``about`` is not provided, fetch post context from
            TikTok's public oEmbed endpoint and pass it as ``about``. Falls back to
            a context-less comment with a stderr warning if oEmbed fails.
        account: TikTok @handle for the ``Account`` field. Explicit > env var > omit.
        reply_to: ``{"author": <@handle>, "text"?: <substring>}`` for a reply to
            an existing top-level comment. ``author`` must be non-empty.

    Returns:
        ``{"comment": <published text>, "hivemq": <publish dict>}``.

    Raises:
        CommentError: On empty/invalid input, generation failure, or publish failure.
    """
    post_url = (post_url or "").strip()
    if not post_url:
        raise CommentError("post_url must not be empty.")

    # If the caller asked for a reply but didn't supply a comment, fall through
    # to AI generation as usual — generate_comment doesn't need reply_to, the
    # AI just writes a regular comment that we then attach ReplyTo to below.
    text = (comment or "").strip()
    if text:
        # Verbatim path. Still match what the agent can actually type unless opted out.
        if ascii_only:
            text = " ".join(text.encode("ascii", "ignore").decode("ascii").split())
    else:
        if not (sentiment and sentiment.strip()):
            raise CommentError(
                "Provide either a verbatim comment or a sentiment to generate one."
            )
        # Auto-context: when the caller didn't describe the post, grab its caption
        # (with hashtags) from oEmbed so the AI doesn't guess wildly.
        if about is None and auto_context:
            fetched = _fetch_post_context(post_url)
            if fetched:
                about = fetched
        from comment_generator import generate_comment, CommentGenError
        try:
            text = generate_comment(
                sentiment,
                about=about,
                language=language,
                model=model,
                ascii_only=ascii_only,
            )
        except CommentGenError as e:
            raise CommentError(f"Comment generation failed: {e}") from e

    if not text:
        raise CommentError("Comment is empty after cleaning; nothing to publish.")

    # Build a normalised reply_to dict so the publisher's validation runs on
    # consistent types (the publisher accepts an optional dict; we only pass it
    # when the caller actually asked for a reply, otherwise None).
    rt: Optional[dict] = None
    if reply_to is not None:
        if not isinstance(reply_to, dict):
            raise CommentError("reply_to must be a dict {'author': <@handle>, 'text'?: <substring>}")
        author = (reply_to.get("author") or "").strip()
        if not author:
            raise CommentError("reply_to['author'] must be non-empty (the agent drops such messages).")
        rt = {"author": author}
        raw_text = reply_to.get("text")
        if raw_text is not None and str(raw_text).strip():
            rt["text"] = str(raw_text).strip()

    from hivemq_publisher import publish_comment, HiveMQError
    try:
        info = publish_comment(
            post_url,
            text,
            account=account,
            reply_to=rt,
            topic=topic,
        )
    except HiveMQError as e:
        raise CommentError(f"HiveMQ publish failed: {e}") from e

    return {"comment": text, "hivemq": info}


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="AI-generate (or pass) a comment and publish it to the tiktok/comments topic."
    )
    parser.add_argument("post_url", help="Full TikTok post URL to comment on")
    parser.add_argument("--sentiment", default=None, help='Tone/intent for AI generation, e.g. "positive", "negative"')
    parser.add_argument("--comment", default=None, help="Exact comment text (skips AI generation)")
    parser.add_argument("--about", default=None, help="Short note about what the post is about (AI relevance)")
    parser.add_argument("--language", "--lang", dest="language", default=DEFAULT_LANGUAGE, help=f"AI comment language: id or en (default: {DEFAULT_LANGUAGE})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model for AI generation (default: {DEFAULT_MODEL})")
    parser.add_argument("--keep-non-ascii", action="store_true", help="Do NOT strip non-ASCII (the agent strips it anyway when typing)")
    parser.add_argument("--topic", default=None, help="MQTT topic (default: HIVEMQ_COMMENT_TOPIC or tiktok/comments)")
    parser.add_argument("--no-auto-context", dest="auto_context", action="store_false", help="Skip the oEmbed auto-context fetch (default: fetch and use as --about when --about is not given)")
    parser.add_argument("--account", default=None, help="TikTok @handle (e.g. @captgani) — agent switches account before commenting. Default: TIKTOK_ACCOUNT env var, else omitted.")
    parser.add_argument("--reply-to-author", dest="reply_to_author", default=None, help="Reply to this comment author (the @handle from a comments-list message). Requires --reply-to-text when the same author has multiple comments on the post. Implies ReplyTo is set on the published message.")
    parser.add_argument("--reply-to-text", dest="reply_to_text", default=None, help="Substring of the target comment's text — disambiguates when --reply-to-author has multiple comments. Optional but recommended.")
    parser.add_argument("--json", action="store_true", help="Print the full result JSON")
    args = parser.parse_args()

    # Build reply_to dict from the two CLI flags (only when --reply-to-author was
    # given; --reply-to-text alone is ignored so we don't silently mis-construct).
    reply_to: Optional[dict] = None
    if args.reply_to_author:
        reply_to = {"author": args.reply_to_author}
        if args.reply_to_text:
            reply_to["text"] = args.reply_to_text

    try:
        result = comment_on_post(
            args.post_url,
            sentiment=args.sentiment,
            comment=args.comment,
            about=args.about,
            language=args.language,
            model=args.model,
            ascii_only=not args.keep_non_ascii,
            topic=args.topic,
            auto_context=args.auto_context,
            account=args.account,
            reply_to=reply_to,
        )
    except CommentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Comment: {result['comment']}")
        print(f"Published to {result['hivemq']['topic']} (mid={result['hivemq']['mid']})")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
