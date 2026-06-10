---
name: tiktok-reply-comment
description: Read a TikTok post's existing comments, AI-generate a short reply to each (with a per-comment ReplyTo), and publish them on the tiktok/comments topic. The downstream tiktok-agent opens the post, finds the target comment in the comment sheet, taps Reply, and types the text. Use when you have a TikTok post URL and want to leave a small batch of thoughtful replies (default cap 5/run) on it. Skips already-replied comments via a state file so re-runs don't spam. Requires HIVEMQ_HOST/HIVEMQ_USERNAME/HIVEMQ_PASSWORD, TOKENROUTER_API_KEY, and (optionally) TIKTOK_ACCOUNT.
---

# TikTok Reply-to-Comment (read-then-reply loop)

Reads a post's existing comments and publishes a small batch of AI-written
**replies** to each. The flow is a request/response over MQTT, plus N publishes:

```
backend ──▶ tiktok/comments-read   { "PostURL": "...", "max": 10 }
reader  ──▶ tiktok/comments-list   { "PostURL": "...", "comments": [{author,text}, ...], "count": N, "ts": ... }
backend  (AI-writes a reply per comment, deduping via state file)
backend ──▶ tiktok/comments        { "PostURL": "...", "Comment": "...", "ReplyTo": {author, text}, "Account": "@..." }   × N
commenter──▶ tiktok/comment-status { "PostURL": "...", "status": "commented" | "wrong_account" | "comment_not_found" | ... }
```

This skill owns the **stateful** bits of the loop: the read-job + the
per-reply publish, the dedup state file, the AI prompt tailored to "react to
THIS comment", and the post-context auto-fetch (TikTok oEmbed). The reader
and the commenter are stateless — all policy lives here.

## Requirements

- `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD` — the broker (same as the
  rest of the pipeline). Optional: `HIVEMQ_PORT` (default 8883),
  `HIVEMQ_COMMENT_READ_TOPIC` (default `tiktok/comments-read`),
  `HIVEMQ_COMMENT_LIST_TOPIC` (default `tiktok/comments-list`),
  `HIVEMQ_COMMENT_TOPIC` (default `tiktok/comments`).
- `TOKENROUTER_API_KEY` — for the AI reply generation (same Anthropic model
  route as the rest of the pipeline; default `anthropic/claude-haiku-4.5`).
- `TIKTOK_ACCOUNT` — optional. The `@handle` to add to every published reply
  as the `Account` field. The downstream tiktok-agent switches to it before
  commenting; if the account can't be made active it reports `wrong_account`
  and does not comment. Resolution order: `--account <HANDLE>` on the CLI
  wins, else this env var, else the field is omitted. Set per-run (e.g.
  `TIKTOK_ACCOUNT=@captgani uv run tiktok-reply-comment ...`) — only one
  value at a time.
- `uv` recommended — the inline PEP 723 header auto-installs `paho-mqtt`.

## Run

```bash
# Default: read up to 10 comments, reply to up to 5 (skipping already-replied)
uv run scripts/reply_to_comment.py https://www.tiktok.com/@user/video/123

# Pick sentiment + cap
uv run scripts/reply_to_comment.py <url> --sentiment grateful --max-replies 3

# Reply in English, set Account, override the state file
uv run scripts/reply_to_comment.py <url> --language en --account @captgani \
    --state-file /var/lib/tiktok/replied.json

# Preview what a run would do (no publish, no state update)
uv run scripts/reply_to_comment.py <url> --sentiment friendly --dry-run --json

# Wipe the dedup state and re-reply to everything (e.g. the post was deleted)
uv run scripts/reply_to_comment.py <url> --reset-state
```

Without `uv`: `pip install paho-mqtt` then `python3 scripts/reply_to_comment.py ...`.

## Flags

- `post_url` (positional) — full TikTok post URL to read + reply to.
- `--sentiment TEXT` — tone/intent for the AI reply, e.g. `friendly`, `grateful`,
  `supportive`, `answer a question`, `witty`. Default `friendly`.
- `--max-replies N` — hard cap on replies published per run. Default `5`.
- `--max-comments N` — cap on how many comments the reader scrapes. Default
  `10` (the reader's own default; the contract recommends staying small
  because one phone, sequential).
- `--language id|en` — reply language (default `id`, Indonesian). `image_prompt`
  always stays English; reply language tracks this flag.
- `--model NAME` — TokenRouter model for the AI reply (default
  `anthropic/claude-haiku-4.5`).
- `--account HANDLE` — TikTok `@handle` for the `Account` field. Resolved via
  the same chain as the post publisher (explicit > `TIKTOK_ACCOUNT` env > omit).
- `--about TEXT` — short note about what the post is about (overrides the
  auto-fetched oEmbed context for AI grounding).
- `--no-auto-context` — skip the oEmbed auto-context fetch (default: fetch and
  use as `--about` when `--about` is not given).
- `--state-file PATH` — dedup state file. Default `.tiktok-replied.json` in
  the cwd. Pass empty string `''` to disable dedup across runs (only useful
  for testing). Replied comments are keyed by `(post_url, author, text)`
  (author matched case-insensitively with leading `@` ignored; text matched
  case-insensitively after whitespace collapse).
- `--reset-state` — ignore the existing state file and overwrite it at the
  end. Use when the post was deleted and you want a clean re-reply pass.
- `--read-timeout SEC` — seconds to wait for the reader's comment-list response
  (default `120`). The reader typically takes 5-30 s to scrape.
- `--read-topic TOPIC` — override the read-job topic.
- `--comment-topic TOPIC` — override the comment-publish topic.
- `--keep-non-ascii` — don't strip non-ASCII. Off by default: the agent types
  via `adb input text`, which can't enter emoji / accented characters (it
  strips them, and submits nothing if nothing typeable remains).
- `--dry-run` — generate replies + show payloads, but do NOT publish or
  update state. The `--json` output is the same shape as a real run.
- `--json` — print the full result JSON (counts + per-reply details).

## Output & errors

Default output: post URL, sentiment, Account, reader scrape count, skip
counts (`already_replied`, `own_account`, `no_text`, `ai_error`,
`publish_error`), and one line per published reply showing the author,
reply text, and broker message id. With `--json` the full result dict
includes the raw scraped comments and per-reply HiveMQ publish info.

The skill **fails fast** for unrecoverable issues (empty post URL, bad
sentiment, read-job publish failure, reader-reported error, read timeout,
all candidates failing). It is **forgiving** for per-comment issues: one
comment's AI error or publish error skips that comment and continues — the
run exits 0 and the skips are counted in the result.

## Delivery (contract notes)

The read-job publishes at QoS 1, `retain=false`; the reader runs a durable
QoS-1 session so a read-job published while the device is offline is queued
and delivered on reconnect. Each per-reply publish is also QoS 1,
`retain=false`, and keyed by `PostURL` (no `id` and no `CreatedAt` on comment
messages — the agent acks via the MQTT message id). Delivery is
at-least-once, so a redelivered publish can produce a duplicate reply; the
state file's `(post_url, author, text)` dedup catches that on subsequent
reads, but a back-to-back run on the same post WILL re-reply if the device
redelivers (mitigation: keep `--read-timeout` short and don't run twice in
a row on the same post).

The agent reports per-reply status to `tiktok/comment-status` keyed by
`PostURL` (one status per reply):

| `status` | Meaning |
|----------|---------|
| `commented` | Reply typed and submitted successfully. |
| `needs_manual` | A screen wasn't recognised; the agent stopped. Republish to retry. |
| `skipped_non_ascii` | Nothing typeable remained after stripping non-ASCII; not submitted. |
| `wrong_account` | The target `Account` couldn't be made active; nothing was commented. |
| `comment_not_found` | `ReplyTo` was set but the target comment wasn't found in the sheet. |
| `failed` | Could not open the post / adb error. |

## One-off replies (no read loop)

For replying to a single specific comment without scraping the whole thread,
use the [`tiktok-comment`](../tiktok-comment/SKILL.md) skill with
`--reply-to-author <@handle>` (and optionally `--reply-to-text <substring>`).
That skill now also accepts `--account` for the same Account-field reason.

## Dedup state format

The state file is a plain JSON object you can read / inspect / hand-edit:

```json
{
  "version": 1,
  "replied": [
    {
      "post_url": "https://www.tiktok.com/@user/video/123",
      "author": "user210320127",
      "text": "tapi ko aku makin plenger aja ya",
      "reply": "Iya kak, emang gitu..."
    }
  ]
}
```

Writes are atomic (temp + `os.replace`) — a crash mid-write leaves the
previous file intact. A corrupt file is treated as empty (with a stderr
warning) rather than failing the run, so a stray hand-edit can't block
replies.
