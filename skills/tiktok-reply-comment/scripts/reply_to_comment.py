#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["paho-mqtt>=2.0"]
# ///
"""
Reply to existing comments on a TikTok post (read-then-reply loop).

Ties the read-comments + comment-on-post contracts together:

  1. ``hivemq_publisher.publish_comment_read`` — publish a read-job to
     ``tiktok/comments-read``; the downstream tiktok-comment-reader consumer opens
     the post on the phone, scrapes up to ``max`` top-level comments, and
     publishes a list to ``tiktok/comments-list``.
  2. ``hivemq_publisher.read_comment_list`` — subscribe to ``tiktok/comments-list``
     and wait for the matching response (correlated by ``PostURL``).
  3. ``comment_generator.generate_reply`` — for each comment we haven't already
     replied to, AI-write a short reply that addresses that specific comment.
  4. ``hivemq_publisher.publish_comment`` — publish each reply with ``ReplyTo``
     set to ``{author, text?}`` (the same author/text the model was shown), so
     the downstream tiktok-agent opens the post, finds the target comment in
     the sheet, taps Reply, and types the text.
  5. State file (``.tiktok-replied.json`` by default) records every
     ``(post_url, author, text)`` triple we replied to, so re-runs don't
     re-reply.

This app is a "leave N thoughtful replies" tool, not a "spam every comment"
tool — the state file plus a default ``--max-replies 5`` cap keeps one run
well-behaved on any post. The contract (tiktok-agent
``docs/comment-on-post.md`` / ``docs/read-comments.md``) is clear that the
backend owns dedup policy; the agent and reader are stateless.

Credentials are read from the environment (or a local .env):
  - HIVEMQ_HOST / HIVEMQ_USERNAME / HIVEMQ_PASSWORD   (broker)
  - TOKENROUTER_API_KEY                               (AI reply generation)
  - TIKTOK_ACCOUNT                                    (optional @handle for Account field)

Usage (CLI):
    # Default: read up to 10 comments, reply to up to 5 (skipping already-replied)
    python reply_to_comment.py https://www.tiktok.com/@user/video/123

    # Specify sentiment and reply count
    python reply_to_comment.py <url> --sentiment grateful --max-replies 3

    # Reply in English, set Account, override the state file location
    python reply_to_comment.py <url> --language en --account @captgani --state-file ./state.json

    # Dry-run: generate replies + show payloads, but do NOT publish
    python reply_to_comment.py <url> --sentiment friendly --dry-run

    # Reset the dedup state (e.g. if you wiped the post and want to re-reply)
    python reply_to_comment.py <url> --reset-state

Usage (as a module):
    from reply_to_comment import reply_to_comments
    result = reply_to_comments("https://www.tiktok.com/@user/video/123", sentiment="friendly")
    print(result["replied_count"], result["skipped_already_replied"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


# Defaults mirrored from comment_generator so callers/CLI don't have to import it.
DEFAULT_LANGUAGE = "id"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_SENTIMENT = "friendly"
DEFAULT_MAX_REPLIES = 5
DEFAULT_MAX_COMMENTS = 10
DEFAULT_READ_TIMEOUT = 120  # seconds to wait for the reader's comment-list response
DEFAULT_STATE_FILE = ".tiktok-replied.json"
STATE_FILE_VERSION = 1

# Public, no-auth TikTok oEmbed endpoint — same trick comment_on_post.py uses:
# returns {title, author_name, ...} for any public post; we hand the title to the
# AI as `about` so the reply has grounding if the comment itself is ambiguous.
OEMBED_URL = "https://www.tiktok.com/oembed"
OEMBED_TIMEOUT = 10


class ReplyError(Exception):
    """Raised when the read-then-reply loop fails."""


# ---------------------------------------------------------------------------
# State file — durable dedup of (post_url, author, text) tuples we replied to.
# ---------------------------------------------------------------------------


def _normalize_author(author: str) -> str:
    """Canonical form for dedup: strip, drop leading @, lowercase.

    The agent's ReplyTo matching is case-insensitive on author, so we dedup the
    same way to make sure any casing variation of "User210320127" still blocks
    a duplicate reply.
    """
    return (author or "").strip().lstrip("@").lower()


def _normalize_text(text: str) -> str:
    """Canonical form for dedup: strip + collapse whitespace + lowercase."""
    return " ".join((text or "").split()).lower()


def _state_key(post_url: str, author: str, text: str) -> tuple:
    """The dedup tuple. Two replies collide iff all three normalised fields match."""
    return (_normalize_text(post_url), _normalize_author(author), _normalize_text(text))


def load_state(path: str) -> dict:
    """Load the dedup state file. Returns the default state on missing/corrupt.

    Default state is ``{"version": STATE_FILE_VERSION, "replied": []}``. Corrupt
    JSON is logged to stderr and treated as missing (rebuild from empty) — we'd
    rather risk one duplicate reply than refuse to run because a hand-edit broke
    the file.
    """
    if not path or not os.path.exists(path):
        return {"version": STATE_FILE_VERSION, "replied": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"Warning: could not parse state file {path!r} ({e.__class__.__name__}: {e}); "
            f"starting with an empty state.",
            file=sys.stderr,
        )
        return {"version": STATE_FILE_VERSION, "replied": []}
    if not isinstance(data, dict) or "replied" not in data or not isinstance(data["replied"], list):
        print(
            f"Warning: state file {path!r} has unexpected shape; starting empty.",
            file=sys.stderr,
        )
        return {"version": STATE_FILE_VERSION, "replied": []}
    return data


def save_state(path: str, state: dict) -> None:
    """Atomic-write the dedup state. Writes to ``<path>.tmp`` then renames so a
    crash mid-write doesn't leave a half-written file that future runs treat as
    corrupt. ``os.replace`` is atomic on POSIX (and on Windows in Python 3.3+)."""
    if not path:
        return  # disabled by the caller (state_file="")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Post context (oEmbed auto-fetch, same trick comment_on_post.py uses)
# ---------------------------------------------------------------------------


def _fetch_post_context(post_url: str) -> Optional[str]:
    """Fetch the post's title from TikTok oEmbed for AI context. Returns None
    on any failure (private post, network error, etc.) so the caller can fall
    back to a context-less reply."""
    try:
        qs = urllib.parse.urlencode({"url": post_url})
        req = urllib.request.Request(
            f"{OEMBED_URL}?{qs}",
            headers={"User-Agent": "tiktok-reply-comment/1.0 (+oembed-context)"},
        )
        with urllib.request.urlopen(req, timeout=OEMBED_TIMEOUT) as r:
            data = json.loads(r.read())
        title = (data.get("title") or "").strip()
        title = " ".join(title.split())  # collapse whitespace
        return title or None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(
            f"Warning: oEmbed auto-context failed ({e.__class__.__name__}); "
            f"replying without post context.",
            file=sys.stderr,
        )
        return None


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def reply_to_comments(
    post_url: str,
    *,
    sentiment: str = DEFAULT_SENTIMENT,
    max_replies: int = DEFAULT_MAX_REPLIES,
    max_comments: int = DEFAULT_MAX_COMMENTS,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    account: Optional[str] = None,
    about: Optional[str] = None,
    state_file: str = DEFAULT_STATE_FILE,
    reset_state: bool = False,
    auto_context: bool = True,
    ascii_only: bool = True,
    read_timeout: int = DEFAULT_READ_TIMEOUT,
    read_topic: Optional[str] = None,
    comment_topic: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Read a post's comments, generate up to ``max_replies`` replies, and publish
    each one to ``tiktok/comments`` with ``ReplyTo`` set.

    The full flow:

      1. Publish a read-job to ``tiktok/comments-read`` (capped at ``max_comments``).
      2. Wait up to ``read_timeout`` seconds for the matching comment-list response.
      3. Filter the list — drop comments we've already replied to (state file),
         drop empty-text / non-text comments, and (when ``account`` is set) drop
         the caller's own top-level comments so we don't reply to ourselves.
      4. Take the first ``max_replies`` from the filtered list.
      5. For each, generate a reply via ``generate_reply`` (post context from
         oEmbed when ``about`` is not given and ``auto_context`` is True).
      6. Publish each reply with ``ReplyTo={author, text?}`` (unless ``dry_run``).
      7. Append the new (post_url, author, text) tuples to the state file
         (atomic write).

    The function is forgiving: a single per-comment failure (AI error, publish
    error) skips that comment and moves on. The function only raises on:

      - empty ``post_url`` / sentiment / ``max_replies < 1`` / ``max_comments < 1``
      - the read-job publish failing (we never got a chance to know what to reply to)
      - the reader's response erroring (``error`` key set on the comment-list)
      - the read timeout being exceeded
      - every candidate comment failing (i.e. zero replies made it through)

    Args:
        post_url: Full TikTok post URL whose comments to read + reply to.
        sentiment: Tone/intent passed to ``generate_reply``.
        max_replies: Hard cap on the number of replies published per run.
        max_comments: Cap on the number of comments the reader scrapes
            (forwarded to ``publish_comment_read(max=...)``).
        language: Reply language — ``"id"`` (Indonesian, default) or ``"en"``.
        model: TokenRouter model for ``generate_reply``.
        account: TikTok @handle for the ``Account`` field on every published
            reply. Resolved via ``resolve_account`` (explicit > env var > omit).
        about: Post context for the AI. When None and ``auto_context`` is True,
            fetched from TikTok oEmbed.
        state_file: Path to the dedup state file. Empty string disables state
            (no dedup across runs — only useful for testing).
        reset_state: When True, ignore the existing state file (don't load it)
            and overwrite it at the end. Use when the post was deleted and you
            want a clean re-reply pass.
        auto_context: When True and ``about`` is not given, fetch the post's
            caption from oEmbed and pass it as ``about``.
        ascii_only: Strip non-ASCII from generated replies.
        read_timeout: Seconds to wait for the comment-list response.
        read_topic: Override ``HIVEMQ_COMMENT_READ_TOPIC``.
        comment_topic: Override ``HIVEMQ_COMMENT_TOPIC``.
        dry_run: When True, generate replies and build the payloads but DO NOT
            publish them. The state file is also not updated. Used to preview
            what a run would do.

    Returns:
        A result dict:
        ``{
            "post_url": str,
            "sentiment": str,
            "account": str | None,
            "read": {"topic": str, "mid": int, "comments": [...], "count": N},
            "candidates": int,            # comments considered for reply
            "replied": [                  # successfully published replies
                {"author": str, "text": str, "reply": str, "hivemq": {...}},
                ...
            ],
            "skipped_already_replied": int,
            "skipped_own_account": int,
            "skipped_no_text": int,
            "skipped_ai_error": int,
            "skipped_publish_error": int,
            "state_file": str,
            "dry_run": bool,
        }``

    Raises:
        ReplyError: On the validation, read, or "all candidates failed" cases
            listed in the function-level docstring. Per-comment failures are
            counted in the result dict, not raised.
    """
    post_url = (post_url or "").strip()
    if not post_url:
        raise ReplyError("post_url must not be empty.")
    if not sentiment or not sentiment.strip():
        raise ReplyError("sentiment must not be empty.")
    if max_replies < 1:
        raise ReplyError(f"max_replies must be >= 1, got {max_replies}")
    if max_comments < 1:
        raise ReplyError(f"max_comments must be >= 1, got {max_comments}")

    from hivemq_publisher import (
        publish_comment,
        publish_comment_read,
        read_comment_list,
        resolve_account,
        HiveMQError,
    )
    from comment_generator import generate_reply, CommentGenError

    # Resolve Account once for the whole loop — the contract sends one
    # Account per comment message, and we always want the same one.
    resolved_account = resolve_account(explicit=account)

    # 1. Publish the read-job.
    try:
        read_job = publish_comment_read(post_url, max_comments=max_comments, topic=read_topic)
    except HiveMQError as e:
        raise ReplyError(f"Failed to publish read-job: {e}") from e

    # 2. Wait for the matching comment-list response.
    try:
        listing = read_comment_list(post_url, timeout=read_timeout, topic=read_topic)
    except HiveMQError as e:
        raise ReplyError(f"Failed to read comment list: {e}") from e

    # 3. Branch on the reader's status.
    if listing.get("error"):
        # Reader's own error (couldn't open the post, screen not recognised, etc.).
        # Per the contract, the reader drops the job after one error — re-reading
        # the same post will hit the same error. Surface it to the caller.
        raise ReplyError(
            f"Reader reported an error for {post_url}: {listing.get('error')!r}. "
            f"The reader drops the job on error; you'll need to retry later."
        )

    raw_comments = listing.get("comments") or []
    if not isinstance(raw_comments, list):
        raise ReplyError(f"Reader returned unexpected comments shape: {type(raw_comments).__name__}")

    # 4. Load dedup state, build the seen-set, filter the list.
    state = {"version": STATE_FILE_VERSION, "replied": []} if reset_state else load_state(state_file)
    seen: set = set()
    for entry in state.get("replied", []):
        if not isinstance(entry, dict):
            continue
        try:
            seen.add(_state_key(entry.get("post_url", ""), entry.get("author", ""), entry.get("text", "")))
        except Exception:
            continue

    candidates = []
    skipped_already_replied = 0
    skipped_own_account = 0
    skipped_no_text = 0
    for c in raw_comments:
        if not isinstance(c, dict):
            continue
        author = (c.get("author") or "").strip()
        text = (c.get("text") or "").strip()
        if not text:
            skipped_no_text += 1
            continue
        if not author:
            # No author means we can't ReplyTo — the agent would drop the message.
            skipped_no_text += 1
            continue
        if resolved_account and _normalize_author(author) == _normalize_author(resolved_account):
            # Don't reply to our own top-level comments (we'd just be talking to
            # ourselves). The reader filters out our NESTED replies, but a
            # top-level comment we left earlier would still appear here.
            skipped_own_account += 1
            continue
        key = _state_key(post_url, author, text)
        if key in seen:
            skipped_already_replied += 1
            continue
        candidates.append(c)

    # 5. Auto-context for the AI (fetch once, share across all replies).
    resolved_about = about
    if resolved_about is None and auto_context:
        resolved_about = _fetch_post_context(post_url)

    # 6. Cap to max_replies and process.
    selected = candidates[:max_replies]
    replied: list = []
    skipped_ai_error = 0
    skipped_publish_error = 0
    new_state_entries: list = []

    for c in selected:
        author = (c.get("author") or "").strip()
        text = (c.get("text") or "").strip()

        # Generate the reply text.
        try:
            reply_text = generate_reply(
                sentiment,
                comment_text=text,
                comment_author=author,
                about=resolved_about,
                language=language,
                model=model,
                ascii_only=ascii_only,
            )
        except CommentGenError as e:
            print(
                f"Warning: reply generation failed for @{_normalize_author(author)} "
                f"({text!r:.60}): {e}",
                file=sys.stderr,
            )
            skipped_ai_error += 1
            continue

        reply_to = {"author": author, "text": text}

        if dry_run:
            # Don't publish, don't update state — just record the planned reply.
            replied.append(
                {
                    "author": author,
                    "text": text,
                    "reply": reply_text,
                    "hivemq": None,
                    "dry_run": True,
                }
            )
            new_state_entries.append(
                {"post_url": post_url, "author": author, "text": text, "reply": reply_text, "dry_run": True}
            )
            continue

        # Publish.
        try:
            info = publish_comment(
                post_url,
                reply_text,
                account=resolved_account or None,
                reply_to=reply_to,
                topic=comment_topic,
            )
        except HiveMQError as e:
            print(
                f"Warning: publish failed for @{_normalize_author(author)}: {e}",
                file=sys.stderr,
            )
            skipped_publish_error += 1
            continue

        replied.append(
            {
                "author": author,
                "text": text,
                "reply": reply_text,
                "hivemq": info,
            }
        )
        new_state_entries.append(
            {"post_url": post_url, "author": author, "text": text, "reply": reply_text}
        )

    # 7. Update state (atomic write) — even on partial failure, every successful
    # reply lands in the state file so we don't re-reply next run.
    if state_file and not dry_run and new_state_entries:
        state.setdefault("replied", [])
        state["replied"].extend(new_state_entries)
        try:
            save_state(state_file, state)
        except OSError as e:
            # State write failure is non-fatal: the publishes already happened,
            # and the next run will re-reply to these (then dedup correctly
            # going forward). Just warn.
            print(
                f"Warning: could not write state file {state_file!r}: {e}. "
                f"Next run may re-reply to the same comments.",
                file=sys.stderr,
            )

    result = {
        "post_url": post_url,
        "sentiment": sentiment,
        "account": resolved_account or None,
        "read": {
            "topic": read_job.get("topic"),
            "mid": read_job.get("mid"),
            "comments": raw_comments,
            "count": len(raw_comments),
        },
        "candidates": len(candidates),
        "replied": replied,
        "skipped_already_replied": skipped_already_replied,
        "skipped_own_account": skipped_own_account,
        "skipped_no_text": skipped_no_text,
        "skipped_ai_error": skipped_ai_error,
        "skipped_publish_error": skipped_publish_error,
        "state_file": state_file or None,
        "dry_run": dry_run,
    }

    # Surface "everything failed" as a hard error so the caller exits non-zero.
    # Partial success (some replies made it, some failed) is a normal completion
    # with skips counted in the result.
    if candidates and not replied and not dry_run:
        raise ReplyError(
            f"All {len(candidates)} candidate comments failed "
            f"(ai_errors={skipped_ai_error}, publish_errors={skipped_publish_error})."
        )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description=(
            "Read a post's comments, AI-generate up to N replies, and publish each "
            "as a Reply on the tiktok/comments topic. Skips already-replied comments "
            "via a state file so re-runs don't spam."
        )
    )
    parser.add_argument("post_url", help="Full TikTok post URL to read + reply to")
    parser.add_argument("--sentiment", default=DEFAULT_SENTIMENT, help=f"Tone/intent for the reply (default: {DEFAULT_SENTIMENT})")
    parser.add_argument("--max-replies", type=int, default=DEFAULT_MAX_REPLIES, dest="max_replies", help=f"Cap on replies published per run (default: {DEFAULT_MAX_REPLIES})")
    parser.add_argument("--max-comments", type=int, default=DEFAULT_MAX_COMMENTS, dest="max_comments", help=f"Cap on comments scraped by the reader (default: {DEFAULT_MAX_COMMENTS})")
    parser.add_argument("--language", "--lang", dest="language", default=DEFAULT_LANGUAGE, help=f"Reply language: id (default) or en (default: {DEFAULT_LANGUAGE})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"TokenRouter model for reply generation (default: {DEFAULT_MODEL})")
    parser.add_argument("--account", default=None, help="TikTok @handle (e.g. @captgani) — agent switches account before commenting. Default: TIKTOK_ACCOUNT env var, else omitted.")
    parser.add_argument("--about", default=None, help="Short note about what the post is about (overrides the auto-fetched oEmbed context for AI relevance)")
    parser.add_argument("--no-auto-context", dest="auto_context", action="store_false", help="Skip the oEmbed auto-context fetch (default: fetch and use as --about when --about is not given)")
    parser.add_argument("--state-file", dest="state_file", default=DEFAULT_STATE_FILE, help=f"Dedup state file (default: {DEFAULT_STATE_FILE}). Pass empty string '' to disable.")
    parser.add_argument("--reset-state", dest="reset_state", action="store_true", help="Ignore the existing state file and overwrite it (use when the post was wiped and you want a clean re-reply pass)")
    parser.add_argument("--read-timeout", type=int, dest="read_timeout", default=DEFAULT_READ_TIMEOUT, help=f"Seconds to wait for the comment-list response (default: {DEFAULT_READ_TIMEOUT})")
    parser.add_argument("--read-topic", dest="read_topic", default=None, help="Override HIVEMQ_COMMENT_READ_TOPIC")
    parser.add_argument("--comment-topic", dest="comment_topic", default=None, help="Override HIVEMQ_COMMENT_TOPIC")
    parser.add_argument("--keep-non-ascii", dest="keep_non_ascii", action="store_true", help="Do NOT strip non-ASCII (the agent strips it anyway when typing)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Generate replies + show payloads, but do NOT publish or update state")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Print the full result JSON")
    args = parser.parse_args()

    try:
        result = reply_to_comments(
            args.post_url,
            sentiment=args.sentiment,
            max_replies=args.max_replies,
            max_comments=args.max_comments,
            language=args.language,
            model=args.model,
            account=args.account,
            about=args.about,
            state_file=args.state_file,
            reset_state=args.reset_state,
            auto_context=args.auto_context,
            ascii_only=not args.keep_non_ascii,
            read_timeout=args.read_timeout,
            read_topic=args.read_topic,
            comment_topic=args.comment_topic,
            dry_run=args.dry_run,
        )
    except ReplyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # Compact human summary.
    print(f"Post:      {result['post_url']}")
    print(f"Sentiment: {result['sentiment']}")
    if result["account"]:
        print(f"Account:   {result['account']}")
    print(f"Reader:    scraped {result['read']['count']} comment(s) on {result['read']['topic']}")
    print(f"Skipped:   already_replied={result['skipped_already_replied']} own_account={result['skipped_own_account']} no_text={result['skipped_no_text']} ai_error={result['skipped_ai_error']} publish_error={result['skipped_publish_error']}")
    if result["dry_run"]:
        print(f"Replied:   {len(result['replied'])} (DRY RUN — nothing published, state not updated)")
    else:
        print(f"Replied:   {len(result['replied'])}")
    for r in result["replied"]:
        suffix = "  [dry-run]" if r.get("dry_run") else f"  mid={r['hivemq']['mid']}"
        print(f"  -> @{_normalize_author(r['author'])}: {r['reply']}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
