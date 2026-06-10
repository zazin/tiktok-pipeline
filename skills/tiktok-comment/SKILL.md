---
name: tiktok-comment
description: Comment on an existing TikTok post. AI-writes a comment from a desired sentiment (e.g. positive/negative), or takes exact text, then publishes one {PostURL, Comment} message to the HiveMQ topic tiktok/comments; the downstream tiktok-agent opens the post by URL and leaves the comment. Also supports one-off replies to a specific existing comment via --reply-to-author (and optional --reply-to-text) and the Account field via --account (or TIKTOK_ACCOUNT env var). Use when you have a TikTok post URL and want ONE comment left on it. For batch-replying to many comments on a post, use the tiktok-reply-comment skill instead. Requires HIVEMQ_HOST/HIVEMQ_USERNAME/HIVEMQ_PASSWORD, and TOKENROUTER_API_KEY when generating (not when passing --comment).
---

# TikTok Comment (AI generate + HiveMQ publish)

Leaves a comment on an existing TikTok post. You give a post URL and either a
**sentiment/intent** (the AI writes the comment) or an **exact comment** (published
verbatim). It publishes one `{PostURL, Comment}` JSON message on topic
`tiktok/comments`; the downstream tiktok-agent subscribes, opens the post by URL,
and types the comment (contract: tiktok-agent `docs/comment-on-post.md`).

This skill also supports **one-off replies** to a specific existing comment via
`--reply-to-author <@handle>` (and optionally `--reply-to-text <substring>`) — the
agent opens the post, finds the target comment in the sheet, taps Reply, and types
your text. For the **read-then-reply loop** (read the post's comments and reply
to several of them in one run) use the [`tiktok-reply-comment`](../tiktok-reply-comment/SKILL.md)
skill instead.

This skill never looks at the post itself. By default it auto-fetches the post's
caption + hashtags from TikTok's public oEmbed endpoint and uses that as the AI's
context, so even with no `--about` the generated comment is on-topic. Pass `--about`
to override the auto-fetched context, or `--no-auto-context` to skip the fetch
entirely.

## Requirements

- `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD` — the HiveMQ Cloud publish.
  Optional: `HIVEMQ_PORT` (default 8883), `HIVEMQ_COMMENT_TOPIC` (default
  `tiktok/comments`). The comment publisher always uses a broker-assigned client id
  (it ignores `HIVEMQ_CLIENT_ID`) so it can't collide with the agent's client id.
- `TOKENROUTER_API_KEY` — only when generating from `--sentiment` (not needed with
  `--comment`).
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `paho-mqtt`.

## Run

```bash
# AI-generate a positive comment and publish it
uv run scripts/comment_on_post.py https://www.tiktok.com/@user/video/123 --sentiment positive

# give the AI context for a more relevant comment
uv run scripts/comment_on_post.py <url> --sentiment negative --about "a 12-step skincare routine"

# publish an exact comment verbatim (no AI, no TOKENROUTER_API_KEY needed)
uv run scripts/comment_on_post.py <url> --comment "Nice video!"

# one-off reply to a specific existing comment (the agent taps Reply in the sheet)
uv run scripts/comment_on_post.py <url> --comment "Makasih kak!" \
    --reply-to-author user210320127 --reply-to-text "makin plenger"

# leave the comment as a specific TikTok account (else uses TIKTOK_ACCOUNT env var)
uv run scripts/comment_on_post.py <url> --comment "Welcome to the channel!" --account @captgani
```

Without `uv`: `pip install paho-mqtt` then `python3 scripts/comment_on_post.py ...`.

## Flags

- `post_url` (positional) — full TikTok post URL to comment on.
- `--sentiment TEXT` — tone/intent for AI generation, e.g. `positive`, `negative`,
  `ask a question`. Required unless `--comment` is given.
- `--comment TEXT` — exact comment text; skips AI generation.
- `--about TEXT` — short note about what the post is about (overrides the auto-fetched
  oEmbed context for AI generation).
- `--no-auto-context` — skip the oEmbed auto-context fetch (default: fetch and use as
  the AI's `about` when `--about` is not given).
- `--language id|en` — AI comment language (default `id`, Indonesian).
- `--model NAME` — TokenRouter model for generation (default `anthropic/claude-haiku-4.5`).
- `--keep-non-ascii` — don't strip non-ASCII. Off by default: the comment is kept
  ASCII because the agent types it via `adb input text`, which can't enter emoji /
  accented characters (it strips them, and submits nothing if nothing typeable
  remains).
- `--topic TOPIC` — override the comment topic (default `tiktok/comments`).
- `--account HANDLE` — TikTok `@handle` (e.g. `@captgani`) for the `Account` field.
  The agent switches to this account before opening the post; if it can't be
  made active it reports `wrong_account` and does not comment. Default: explicit
  value > `TIKTOK_ACCOUNT` env var > omitted.
- `--reply-to-author HANDLE` — make the comment a *reply* to an existing top-level
  comment by this author. The `author` value comes from a `tiktok/comments-list`
  message (see [`tiktok-reply-comment`](../tiktok-reply-comment/SKILL.md) for the
  loop that produces those). Sets `ReplyTo.author` on the published message.
- `--reply-to-text SUBSTRING` — disambiguates when `--reply-to-author` has multiple
  comments on the post. Optional; matched ASCII-folded.
- `--json` — print the full result JSON.

## Output & errors

Default output: the published comment text and the topic + message id. The publish
is fail-fast for this skill (unlike posting): if the HiveMQ publish fails, the
command exits non-zero. A message with an empty `PostURL` or `Comment` is rejected
before publishing, because the agent drops such messages.

## Delivery (contract notes)

Published at QoS 1, `retain=false`. The agent runs a durable QoS-1 session, so a
comment published while the device is offline is queued by the broker and delivered
on reconnect. Delivery is at-least-once (the agent may act twice on redelivery), so
keep comment text safe to repeat. The agent optionally reports status on
`tiktok/comment-status`, keyed by `PostURL`.
