#!/usr/bin/env python3
"""
HiveMQ publisher module.

Publishes one MQTT message per generated TikTok post to a HiveMQ Cloud broker. The
downstream tiktok-agent (separate repo) subscribes to the topic and posts the
content — so this HiveMQ message is the pipeline's hand-off to the agent.

Delivery is QoS 1 (at-least-once); messages are NOT retained. The agent is expected
to subscribe with a persistent/durable session (a fixed client id and
clean_session=false) so it still receives a backlog after a brief disconnect — that
is the subscriber's concern.

Credentials / target are read from environment variables:
  - HIVEMQ_HOST      — broker host, e.g. "xxxx.s1.eu.hivemq.cloud" (required)
  - HIVEMQ_USERNAME  — broker username (required)
  - HIVEMQ_PASSWORD  — broker password (required)
  - HIVEMQ_PORT      — TLS port. Optional; defaults to 8883.
  - HIVEMQ_TOPIC     — topic to publish to. Optional; defaults to "tiktok/posts".
  - HIVEMQ_CLIENT_ID — MQTT client id. Optional; the broker assigns one when unset.

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


# Default broker port / topic when the matching env vars are unset.
DEFAULT_PORT = 8883
DEFAULT_TOPIC = "tiktok/posts"


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


def _get_client_id() -> str:
    # Optional: empty string lets the broker assign a client id.
    return os.getenv("HIVEMQ_CLIENT_ID") or ""


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
        topic: Override HIVEMQ_TOPIC.
        qos: MQTT quality of service (default 1, at-least-once).
        timeout: Seconds to wait for the broker to acknowledge the publish.

    Returns:
        {"status": "success", "topic": <topic>, "mid": <message id>}.

    Raises:
        HiveMQError: On missing creds, connect failure, or publish timeout.
    """
    host = _get_host()
    user = _get_username()
    pw = _get_password()
    port = _get_port()
    topic = _get_topic(topic)

    # Stamp a unique correlation id and the creation time unless the caller
    # already set them. The agent REQUIRES "id" (it drops messages without one)
    # and echoes it back on the status topic. ISO-8601 UTC for CreatedAt.
    payload = dict(payload)
    payload.setdefault("id", uuid.uuid4().hex)
    payload.setdefault("CreatedAt", datetime.now(timezone.utc).isoformat())
    body = json.dumps(payload, ensure_ascii=False)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=_get_client_id(),
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
