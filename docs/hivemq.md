# HiveMQ — the real-time post trigger

This document describes the MQTT message the TikTok pipeline publishes to HiveMQ Cloud. It is
the reference for the **downstream app** (the separate `tiktok-agent`) that consumes these
messages to post content to TikTok.

## Overview

For every generated post, after the Airtable record is written, the pipeline publishes **one
MQTT message** carrying the same post fields plus the new Airtable record id. This is a
**real-time push trigger** so the agent can react instantly instead of polling Airtable.

Airtable stays the **durable source of truth**: the HiveMQ publish is best-effort and
**non-fatal** — if the broker is unreachable, the run still succeeds (the failure is recorded
in the result dict) and the agent can fall back to polling `Status = "pending"` rows. See
[airtable.md](airtable.md).

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

- **Transport:** MQTT over TLS (system CA certs — HiveMQ Cloud uses a public CA).
- **QoS:** 1 (at-least-once). The publisher waits for the broker `PUBACK` before disconnecting.
- **Retain:** false. (A retained message would only keep the *latest* post per topic, which
  loses a backlog — see the subscriber guidance below.)

## Message payload

The body is JSON (UTF-8), with field names mirroring the Airtable `Posts` columns plus
`AirtableRecordId`:

```json
{
  "AirtableRecordId": "rec0123456789",
  "Idea": "a cat in red boots on a neon street",
  "Caption": "...",
  "Description": "...",
  "ImageURL": "https://ik.imagekit.io/salt/tiktok/tiktok_20260604_230055.jpeg",
  "ImageKitFileId": "660f...",
  "ImagePath": "tiktok_20260604_230055.jpeg",
  "Profile": "kalila",
  "Status": "pending",
  "CreatedAt": "2026-06-07T10:15:30.123456+00:00"
}
```

Only fields with a value are included (besides `Status`, which defaults to `pending`).
`CreatedAt` is an ISO-8601 UTC timestamp stamped at publish time unless the caller supplies one.
Use `AirtableRecordId` to fetch/update the corresponding Airtable row (e.g. flip `Status` to
`posted`/`failed` after posting).

## Subscriber guidance (the tiktok-agent)

Because messages are published at QoS 1 with `retain=false`, the agent should subscribe with a
**persistent / durable session** so it still receives messages queued while it was briefly
offline:

- Use a **fixed `client_id`** (do not let it be random per run).
- Connect with **`clean_session=false`** (MQTT 3.1.1) / `clean_start=false` + a non-zero session
  expiry (MQTT 5) so the broker keeps the subscription and queues missed QoS-1 messages.
- Subscribe to `tiktok/posts` (or the configured `HIVEMQ_TOPIC`) at **QoS 1**.
- On each message, post to TikTok using `ImageURL` + `Caption` + `Description`, then update the
  Airtable row identified by `AirtableRecordId`.

Polling Airtable for `Status = "pending"` rows remains a valid fallback if a message is ever
missed.

## Manual publish (testing)

```bash
uv run hivemq-publish --idea "test" --caption "hello" --status pending --json
```

Subscribe in the HiveMQ Cloud web client (or any MQTT client) to `tiktok/posts` to confirm the
message arrives.
