#!/usr/bin/env python3
"""
HiveMQ publisher module.

Publishes MQTT messages to a HiveMQ Cloud broker for the downstream tiktok-agent
(separate repo), which subscribes and acts on them. Two hand-offs live here:

  - publish_post    — one "new post" message on HIVEMQ_TOPIC ("tiktok/posts");
                      the agent posts the image/caption.
  - publish_comment — one "comment on an existing post" message on
                      HIVEMQ_COMMENT_TOPIC ("tiktok/comments"); the agent opens the
                      post by URL and leaves the given comment. See the contract at
                      tiktok-agent docs/comment-on-post.md.

Delivery is QoS 1 (at-least-once); messages are NOT retained. The agent is expected
to subscribe with a persistent/durable session (a fixed client id and
clean_session=false) so it still receives a backlog after a brief disconnect — that
is the subscriber's concern.

Credentials / target are read from environment variables:
  - HIVEMQ_HOST          — broker host, e.g. "xxxx.s1.eu.hivemq.cloud" (required)
  - HIVEMQ_USERNAME      — broker username (required)
  - HIVEMQ_PASSWORD      — broker password (required)
  - HIVEMQ_PORT          — TLS port. Optional; defaults to 8883.
  - HIVEMQ_TOPIC         — post topic. Optional; defaults to "tiktok/posts".
  - HIVEMQ_COMMENT_TOPIC — comment topic. Optional; defaults to "tiktok/comments".
  - HIVEMQ_CLIENT_ID     — MQTT client id for publish_post. Optional; the broker
                           assigns one when unset. publish_comment ignores this and
                           always uses a broker-assigned id, so it can never collide
                           with the agent's own client ids (e.g. "tiktok-commenter"),
                           which would otherwise disconnect the agent.
  - TIKTOK_ACCOUNT       — optional. TikTok @handle (e.g. "@captgani") to add to
                           every published post as the "Account" field. The
                           downstream tiktok-agent switches to this account
                           via its in-app switcher BEFORE posting; if the
                           account is not active it reports "wrong_account"
                           and does not post. See tiktok-agent
                           docs/post-image.md. Omit to let the agent post as
                           whatever account is currently active. Set per-run
                           (e.g. `TIKTOK_ACCOUNT=@captgani uv run
                           tiktok-pipeline --profile gani ...`) since this
                           repo only supports one value at a time. Explicit
                           "Account" in the payload (or --account on the CLI)
                           wins over this env var. NEVER set to "" — empty
                           == omit.

Usage (CLI):
    python hivemq_publisher.py --idea "a cat in red boots" --caption "..." \
        --image-url https://ik.imagekit.io/salt/x.png --status pending

Usage (as a module):
    from hivemq_publisher import publish_post

    info = publish_post({
        "Idea": "...", "Caption": "...", "ImageURL": "...", "Status": "pending",
    })
    print(info["topic"], info["mid"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt


# Default broker port / topics when the matching env vars are unset.
DEFAULT_PORT = 8883
DEFAULT_TOPIC = "tiktok/posts"
DEFAULT_COMMENT_TOPIC = "tiktok/comments"


class HiveMQError(Exception):
    """Raised when a HiveMQ (MQTT) publish fails."""


def _get_host() -> str:
    host = os.getenv("HIVEMQ_HOST")
    if not host:
        raise HiveMQError(
            "HIVEMQ_HOST env var is not set. "
            "Export it (or add it to .env) before running."
        )
    return host


def _get_username() -> str:
    user = os.getenv("HIVEMQ_USERNAME")
    if not user:
        raise HiveMQError(
            "HIVEMQ_USERNAME env var is not set. "
            "Export it (or add it to .env) before running."
        )
    return user


def _get_password() -> str:
    pw = os.getenv("HIVEMQ_PASSWORD")
    if not pw:
        raise HiveMQError(
            "HIVEMQ_PASSWORD env var is not set. "
            "Export it (or add it to .env) before running."
        )
    return pw


def _get_port() -> int:
    # Optional: falls back to DEFAULT_PORT (8883, TLS) when unset.
    raw = os.getenv("HIVEMQ_PORT")
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError as e:
        raise HiveMQError(f"HIVEMQ_PORT must be an integer, got {raw!r}") from e


def _get_topic(topic: Optional[str] = None) -> str:
    # Optional: falls back to DEFAULT_TOPIC ("tiktok/posts") when unset.
    return topic or os.getenv("HIVEMQ_TOPIC") or DEFAULT_TOPIC


def _get_comment_topic(topic: Optional[str] = None) -> str:
    # Optional: falls back to DEFAULT_COMMENT_TOPIC ("tiktok/comments") when unset.
    return topic or os.getenv("HIVEMQ_COMMENT_TOPIC") or DEFAULT_COMMENT_TOPIC


def _get_client_id() -> str:
    # Optional: empty string lets the broker assign a client id.
    return os.getenv("HIVEMQ_CLIENT_ID") or ""


def _get_account() -> str:
    # Optional. The agent treats an empty/missing "Account" the same (omitted =
    # post as current account), so we strip whitespace and return "" when unset.
    # Caller decides whether to include the field at all — we never inject "".
    return (os.getenv("TIKTOK_ACCOUNT") or "").strip()


def resolve_account(*, explicit: Optional[str] = None) -> str:
    """
    Resolve the TikTok @handle to include as the "Account" field on a published post.

    Lookup order (first non-empty wins):
      1. ``explicit`` (e.g. from ``--account`` on the CLI)
      2. ``TIKTOK_ACCOUNT`` env var

    Returns the empty string when nothing is set; callers must treat "" as
    "omit the Account field entirely" (the agent contract treats empty and
    missing identically, and we never want to send ``"Account": ""``).

    Args:
        explicit: Caller-supplied handle (e.g. CLI --account). Leading/trailing
            whitespace is stripped; an empty / whitespace-only value is treated
            as "not supplied" and falls through to the env var.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()
    return _get_account()


def publish_post(
    payload: dict,
    *,
    topic: Optional[str] = None,
    qos: int = 1,
    timeout: int = 10,
) -> dict:
    """
    Publish a single post message to HiveMQ over a TLS connection.

    Args:
        payload: Mapping serialized to a JSON message body. A unique "id"
            (the agent's required correlation key) and a "CreatedAt" ISO-8601 UTC
            timestamp are added automatically unless the caller supplies them.
            If the payload has no "Account" key, ``TIKTOK_ACCOUNT`` is injected
            (only when set) so callers don't have to thread it through.
        topic: Override HIVEMQ_TOPIC.
        qos: MQTT quality of service (default 1, at-least-once).
        timeout: Seconds to wait for the broker to acknowledge the publish.

    Returns:
        {"status": "success", "topic": <topic>, "mid": <message id>}.

    Raises:
        HiveMQError: On missing creds, connect failure, or publish timeout.
    """
    topic = _get_topic(topic)

    # Stamp a unique correlation id and the creation time unless the caller
    # already set them. The agent REQUIRES "id" (it drops messages without one)
    # and echoes it back on the status topic. ISO-8601 UTC for CreatedAt.
    payload = dict(payload)
    payload.setdefault("id", uuid.uuid4().hex)
    payload.setdefault("CreatedAt", datetime.now(timezone.utc).isoformat())
    # Inject the default Account from TIKTOK_ACCOUNT when the caller didn't
    # supply one. Only inject a non-empty value — an empty "Account" would be
    # ambiguous vs. an omitted field, and the contract treats them the same.
    if "Account" not in payload:
        default_account = _get_account()
        if default_account:
            payload["Account"] = default_account

    return _publish_json(payload, topic, qos=qos, timeout=timeout)


def publish_comment(
    post_url: str,
    comment: str,
    *,
    topic: Optional[str] = None,
    qos: int = 1,
    timeout: int = 10,
) -> dict:
    """
    Publish a single "comment on a post" message to HiveMQ over a TLS connection.

    Per the tiktok-agent contract (docs/comment-on-post.md) the message carries
    exactly two fields — ``PostURL`` and ``Comment`` — and deliberately NO ``id``
    and NO ``CreatedAt`` (the agent acks via the MQTT message id and keys status by
    ``PostURL``). Both fields must be non-empty or the agent drops the message, so
    they are validated here.

    Args:
        post_url: Full TikTok post URL (the comment target / correlation key).
        comment: Exact comment text to submit. The agent types it via ``adb input
            text``, which cannot enter emoji / non-ASCII — keep it ASCII.
        topic: Override HIVEMQ_COMMENT_TOPIC.
        qos: MQTT quality of service (default 1, at-least-once).
        timeout: Seconds to wait for the broker to acknowledge the publish.

    Returns:
        {"status": "success", "topic": <topic>, "mid": <message id>}.

    Raises:
        HiveMQError: On empty PostURL/Comment, missing creds, connect failure, or
            publish timeout.
    """
    post_url = (post_url or "").strip()
    comment = (comment or "").strip()
    if not post_url:
        raise HiveMQError("PostURL must not be empty (the agent drops such messages).")
    if not comment:
        raise HiveMQError("Comment must not be empty (the agent drops such messages).")

    # Always let the broker assign the client id for comments (pass empty), so the
    # comment publisher never reuses HIVEMQ_CLIENT_ID and never risks colliding with
    # the agent's own client id (e.g. "tiktok-commenter"), which would disconnect it.
    payload = {"PostURL": post_url, "Comment": comment}
    return _publish_json(
        payload, _get_comment_topic(topic), qos=qos, timeout=timeout, client_id=""
    )


def _publish_json(
    payload: dict,
    topic: str,
    *,
    qos: int = 1,
    timeout: int = 10,
    client_id: Optional[str] = None,
) -> dict:
    """Connect, publish one JSON message to ``topic``, wait for the ack, disconnect.

    ``client_id`` defaults to HIVEMQ_CLIENT_ID (via _get_client_id); pass "" to force
    a broker-assigned id regardless of the env var.
    """
    host = _get_host()
    user = _get_username()
    pw = _get_password()
    port = _get_port()
    body = json.dumps(payload, ensure_ascii=False)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=_get_client_id() if client_id is None else client_id,
    )
    client.username_pw_set(user, pw)
    client.tls_set()  # system CA certs — HiveMQ Cloud uses a public CA

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        info = client.publish(topic, body, qos=qos)
        info.wait_for_publish(timeout)
        if not info.is_published():
            raise HiveMQError(
                f"publish to {topic!r} timed out before broker ack ({timeout}s)"
            )
    except HiveMQError:
        raise
    except (OSError, ValueError, RuntimeError) as e:
        raise HiveMQError(f"Failed to publish to HiveMQ at {host}:{port}: {e}") from e
    finally:
        client.loop_stop()
        client.disconnect()

    return {"status": "success", "topic": topic, "mid": info.mid}


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Publish one post message to the configured HiveMQ topic."
    )
    parser.add_argument("--idea", default=None, help="Idea (primary field)")
    parser.add_argument("--caption", default=None, help="Caption text")
    parser.add_argument("--description", default=None, help="Description text")
    parser.add_argument("--image-url", default=None, help="Public ImageKit URL")
    parser.add_argument("--file-id", default=None, help="ImageKit file id")
    parser.add_argument("--image-path", default=None, help="Image filename incl. ext (e.g. tiktok_20260604_230055.jpeg)")
    parser.add_argument("--profile", default=None, help="Profile name")
    parser.add_argument("--account", default=None, help="TikTok @handle (e.g. @captgani) — agent switches account before posting. Default: TIKTOK_ACCOUNT env var, else omitted.")
    parser.add_argument("--status", default="pending", help="Status (default: pending)")
    parser.add_argument("--topic", default=None, help="MQTT topic (default: HIVEMQ_TOPIC or tiktok/posts)")
    parser.add_argument("--json", action="store_true", help="Print the full publish-result JSON")
    args = parser.parse_args()

    # Only include fields the user actually provided (besides Status, which defaults).
    field_map = {
        "Idea": args.idea,
        "Caption": args.caption,
        "Description": args.description,
        "ImageURL": args.image_url,
        "ImageKitFileId": args.file_id,
        "ImagePath": args.image_path,
        "Profile": args.profile,
        "Account": args.account,
        "Status": args.status,
    }
    payload = {k: v for k, v in field_map.items() if v is not None}
    if len(payload) <= 1:  # only Status (its default) present
        print("Nothing to publish — pass at least one field flag.", file=sys.stderr)
        return 2

    try:
        info = publish_post(payload, topic=args.topic)
    except HiveMQError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"Published to {info['topic']} (mid={info['mid']})")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
