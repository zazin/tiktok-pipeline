# HiveMQ — the post hand-off

This document describes the MQTT messages the TikTok pipeline publishes to HiveMQ Cloud. It is
the reference for the **downstream app** (the separate `tiktok-agent`) that consumes these
messages to post content, leave comments, and report results.

## Overview

The pipeline publishes to four distinct topics on the same broker, each carrying a different
class of work for the agent:

| Topic | Direction | What it carries |
|-------|-----------|-----------------|
| `tiktok/posts` | out | A new post to publish: image, caption, account, etc. |
| `tiktok/comments` | out | A comment (top-level **or reply**) to leave on a given post. |
| `tiktok/comments-read` | out | A "read this post's comments" job for the comment-reader. |
| `tiktok/comments-list` | in | The reader's reply: a list of scraped top-level comments. |

All four share the same connection / auth / QoS-1 / `retain=false` semantics below; per-topic
payload shapes are detailed in the contract files in `tiktok-agent/docs/` (post-image,
comment-on-post, read-comments).

## Connection / access

The pipeline connects to HiveMQ Cloud over TLS.

| Variable | Purpose |
|----------|---------|
| `HIVEMQ_HOST` | Broker host, e.g. `xxxxxxxx.s1.eu.hivemq.cloud` (required). |
| `HIVEMQ_USERNAME` | Broker username (required). |
| `HIVEMQ_PASSWORD` | Broker password (required). |
| `HIVEMQ_PORT` | TLS port. Optional; defaults to `8883`. |
| `HIVEMQ_TOPIC` | Post topic. Optional; defaults to `tiktok/posts`. |
| `HIVEMQ_COMMENT_TOPIC` | Comment topic (top-level + replies). Optional; defaults to `tiktok/comments`. |
| `HIVEMQ_COMMENT_READ_TOPIC` | Read-job topic (sent to the comment-reader). Optional; defaults to `tiktok/comments-read`. |
| `HIVEMQ_COMMENT_LIST_TOPIC` | Comment-list topic (received from the comment-reader). Optional; defaults to `tiktok/comments-list`. |
| `HIVEMQ_CLIENT_ID` | Publisher MQTT client id for `publish_post` only. Optional; the broker assigns one when unset. `publish_comment`, `publish_comment_read`, and `read_comment_list` all force a per-run client id (uuid-suffixed) so the backend can never collide with the agent's `tiktok-agent`, the commenter's `tiktok-commenter`, or the reader's `tiktok-comment-reader` — any of which would disconnect the peer. |
| `TIKTOK_ACCOUNT` | Optional. TikTok `@handle` (e.g. `@captgani`) to include in every published post + comment as the `Account` field. The agent switches to it before acting; if the account is not active it reports `wrong_account` and does not act. Omit / empty to act as the currently-active account. Explicit `--account` on the CLI wins over this var. Set per-run (e.g. `TIKTOK_ACCOUNT=@captgani uv run tiktok-pipeline --profile gani ...`) since this repo only supports one value at a time. |

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
`Account` is optional — include it (via the `TIKTOK_ACCOUNT` env var, the
`--account` CLI flag, or directly in a programmatic payload) to tell the
downstream `tiktok-agent` which TikTok account to switch to before posting.
`CreatedAt` is an ISO-8601 UTC timestamp stamped at publish time unless the caller supplies one.
`ImageKitFileId` / `ImagePath` uniquely identify the post for de-duplication on the agent side.

## Comment payload (tiktok/comments)

The comment hand-off carries the bare-minimum message plus two optional fields.
Top-level and reply comments share the same topic — the optional `ReplyTo` key
distinguishes them.

Top-level comment (the existing behaviour):

```json
{
  "PostURL": "https://www.tiktok.com/@user/video/123",
  "Comment": "Nice video!",
  "Account": "@captgani"
}
```

Reply to an existing top-level comment (the new behaviour, used by the
`tiktok-reply-comment` skill):

```json
{
  "PostURL": "https://www.tiktok.com/@user/video/123",
  "Comment": "Makasih kak!",
  "Account": "@captgani",
  "ReplyTo": { "author": "user210320127", "text": "makin plenger" }
}
```

- `PostURL` and `Comment` are **required** and must be non-empty (the agent drops messages
  with either empty). The comment is typed via `adb input text` and is therefore
  stripped of non-ASCII / emoji by the agent before typing; a comment with no
  typeable content yields `skipped_non_ascii`.
- `Account` is optional, resolved through the same chain as posts (explicit `--account`
  > `TIKTOK_ACCOUNT` env > omitted). The agent switches to it before opening the
  post; if the account can't be made active it reports `wrong_account` and does
  not comment.
- `ReplyTo` is optional. When present, the comment is submitted as a *reply to*
  the matching top-level comment. `author` is required (the comment's display
  handle, matched case-insensitively with leading `@` ignored); `text` is
  optional and disambiguates when the same author has multiple comments on
  the post (matched ASCII-folded). Replies can only target **top-level**
  comments — not replies-to-replies.
- **No `id` and no `CreatedAt`.** The agent acks via the MQTT message id and
  keys per-comment status by `PostURL`. Status comes back on
  `tiktok/comment-status` (e.g. `commented`, `wrong_account`,
  `comment_not_found`, `needs_manual`, `skipped_non_ascii`, `failed`).

## Read-comments loop (tiktok/comments-read ↔ tiktok/comments-list)

The `tiktok-reply-comment` skill needs to know what comments a post has before
replying — there's no public API for this, so the pipeline uses the downstream
**comment-reader** consumer (client id `tiktok-comment-reader`) to scrape the
sheet on the phone. The flow is request/response over MQTT:

1. Pipeline publishes a read-job to `tiktok/comments-read`:

   ```json
   { "PostURL": "https://www.tiktok.com/@user/video/123", "max": 10 }
   ```

   `PostURL` is required; `max` is optional and caps the reader at N top-level
   comments (default 10; first N from TikTok's relevance-sorted sheet).

2. The reader opens the post on the phone, scrapes the sheet, and publishes
   one response to `tiktok/comments-list`:

   ```json
   {
     "PostURL": "https://www.tiktok.com/@user/video/123",
     "comments": [
       { "author": "user210320127", "text": "tapi ko aku makin plenger aja ya" },
       { "author": "Mas Akbarr",     "text": "makin kesini makin ga guna ni aplikasi" }
     ],
     "count": 2,
     "ts": 1781055659
   }
   ```

   On a read failure the same key set is sent with `comments: []` and an
   `error` field (e.g. `"needs_manual"` or `"failed: <detail>"`). The reader
   drops the job on error so re-reading hits the same error.

3. The pipeline then AI-writes a short reply per comment (skipping ones
   it's already replied to via a local state file) and publishes each as a
   `tiktok/comments` message with `ReplyTo` set to the original
   `{author, text}`.

The reader is read-only and idempotent (re-reading a post just re-publishes
its current comments), and the pipeline uses a transient per-run subscriber
(`client_id = tiktok-reply-<uuid>`) to collect the response — no persistent
session is required for the request/response flow.

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
message arrives. For the comment hand-off:

```bash
# Top-level comment
uv run tiktok-comment https://www.tiktok.com/@user/video/123 --comment "Nice video!" --json

# Reply to a specific existing comment
uv run tiktok-comment <url> --comment "Makasih kak!" --reply-to-author user210320127 --reply-to-text "makin plenger"

# Read a post's comments and reply to up to 5 of them (the read-then-reply loop)
uv run tiktok-reply-comment <url> --sentiment friendly --json
```
