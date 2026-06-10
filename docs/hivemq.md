# HiveMQ — the post hand-off

This document describes the MQTT message the TikTok pipeline publishes to HiveMQ Cloud. It is
the reference for the **downstream app** (the separate `tiktok-agent`) that consumes these
messages to post content to TikTok.

## Overview

For every generated post, after the image is uploaded to ImageKit, the pipeline publishes **one
MQTT message** to a HiveMQ topic carrying the post fields (idea, caption, description, the image
URL + fileId, the image filename, profile, status). This message is the pipeline's hand-off: the
downstream agent subscribes to the topic and posts the content to TikTok.

## Connection / access

The pipeline connects to HiveMQ Cloud over TLS.

| Variable | Purpose |
|----------|---------|
| `HIVEMQ_HOST` | Broker host, e.g. `xxxxxxxx.s1.eu.hivemq.cloud` (required). |
| `HIVEMQ_USERNAME` | Broker username (required). |
| `HIVEMQ_PASSWORD` | Broker password (required). |
| `HIVEMQ_PORT` | TLS port. Optional; defaults to `8883`. |
| `HIVEMQ_TOPIC` | Topic to publish to. Optional; defaults to `tiktok/posts`. |
| `HIVEMQ_CLIENT_ID` | Publisher MQTT client id. Optional; the broker assigns one when unset. |
| `TIKTOK_ACCOUNT` | Optional. Generic fallback for the `Account` field on every published post (a TikTok `@handle`, e.g. `@captgani`). The agent switches to it before posting; if the account is not active it reports `wrong_account` and does not post. Omit / empty to post as the currently-active account. Per-profile defaults (below) take precedence when a profile is active. Explicit `--account` on the CLI wins over both. |
| `TIKTOK_ACCOUNT_<PROFILE>` | Optional per-profile default, where `<PROFILE>` is the profile folder name uppercased (e.g. `TIKTOK_ACCOUNT_GANI`, `TIKTOK_ACCOUNT_KALILA`). When the pipeline runs with `--profile <name>`, the matching `TIKTOK_ACCOUNT_<UPPER(name)>` is used as the `Account` field. Wins over the generic `TIKTOK_ACCOUNT`. Example: `TIKTOK_ACCOUNT_GANI=@captgani`. |

- **Transport:** MQTT over TLS (system CA certs — HiveMQ Cloud uses a public CA).
- **QoS:** 1 (at-least-once). The publisher waits for the broker `PUBACK` before disconnecting.
- **Retain:** false. (A retained message would only keep the *latest* post per topic, which
  loses a backlog — see the subscriber guidance below.)

## Message payload

The body is JSON (UTF-8):

```json
{
  "Idea": "a cat in red boots on a neon street",
  "Caption": "...",
  "Description": "...",
  "ImageURL": "https://ik.imagekit.io/salt/tiktok/tiktok_20260604_230055.jpeg",
  "ImageKitFileId": "660f...",
  "ImagePath": "tiktok_20260604_230055.jpeg",
  "Profile": "kalila",
  "Account": "@captgani",
  "Status": "pending",
  "CreatedAt": "2026-06-07T10:15:30.123456+00:00"
}
```

Only fields with a value are included (besides `Status`, which defaults to `pending`).
`Account` is optional — include it (via the `TIKTOK_ACCOUNT_<PROFILE>` env var when
running with `--profile <name>`, the generic `TIKTOK_ACCOUNT` env var, the
`--account` CLI flag, or directly in a programmatic payload) to tell the
downstream `tiktok-agent` which TikTok account to switch to before posting.
`CreatedAt` is an ISO-8601 UTC timestamp stamped at publish time unless the caller supplies one.
`ImageKitFileId` / `ImagePath` uniquely identify the post for de-duplication on the agent side.

## Subscriber guidance (the tiktok-agent)

Because messages are published at QoS 1 with `retain=false`, the agent should subscribe with a
**persistent / durable session** so it still receives messages queued while it was briefly
offline:

- Use a **fixed `client_id`** (do not let it be random per run).
- Connect with **`clean_session=false`** (MQTT 3.1.1) / `clean_start=false` + a non-zero session
  expiry (MQTT 5) so the broker keeps the subscription and queues missed QoS-1 messages.
- Subscribe to `tiktok/posts` (or the configured `HIVEMQ_TOPIC`) at **QoS 1**.
- On each message, post to TikTok using `ImageURL` + `Caption` + `Description`, and de-dupe on
  `ImageKitFileId` / `ImagePath` so a redelivered message isn't posted twice.

## Manual publish (testing)

```bash
uv run hivemq-publish --idea "test" --caption "hello" --status pending --json
```

Subscribe in the HiveMQ Cloud web client (or any MQTT client) to `tiktok/posts` to confirm the
message arrives.
