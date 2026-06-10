---
name: tiktok-publish
description: Publish a finished image to TikTok by uploading it to ImageKit (public CDN URL) and publishing one Status=pending post message to HiveMQ; the downstream tiktok-agent subscribes to the topic and does the actual posting. Use when an agent has an image file ready and wants it queued for TikTok. Requires IMAGEKIT_PRIVATE_KEY and (unless --no-hivemq) HIVEMQ_HOST/HIVEMQ_USERNAME/HIVEMQ_PASSWORD. Optional TIKTOK_ACCOUNT env var / --account @handle tells the agent which TikTok account to switch to before posting (set TIKTOK_ACCOUNT per-run, e.g. `TIKTOK_ACCOUNT=@captgani uv run tiktok-publish ...`).
---

# TikTok Publish (ImageKit + HiveMQ)

Takes a local image, uploads it to ImageKit, then publishes one post message to
HiveMQ (idea, caption, description, the ImageKit URL + fileId, the image filename,
profile, status — `Status=pending` by default) on topic `tiktok/posts`. That message
is the hand-off: the downstream tiktok-agent subscribes to the topic and posts the
content. Pairs with the `tiktok-image` skill (which only generates the local image).

## Requirements

- `IMAGEKIT_PRIVATE_KEY` — ImageKit upload (Basic-auth username, empty password).
- `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD` — the HiveMQ Cloud publish (not
  needed with `--no-hivemq`). Optional: `HIVEMQ_PORT` (default 8883), `HIVEMQ_TOPIC`
  (default `tiktok/posts`), `HIVEMQ_CLIENT_ID`. The publish is best-effort — a
  failure is reported (and the CLI exits non-zero) but the image still uploads.
- `TIKTOK_ACCOUNT` (optional) — TikTok `@handle` (e.g. `@captgani`) added to
  the published post as the `Account` field. The downstream tiktok-agent
  switches to this account via the in-app switcher **before** posting; if the
  account is not active it reports `wrong_account` and does **not** post.
  Omit / empty = post as the currently-active account. `--account` overrides
  this env var. Set per-run (e.g. `TIKTOK_ACCOUNT=@captgani uv run
  tiktok-publish ...`) since this repo only supports one value at a time. See
  the contract: tiktok-agent `docs/post-image.md`.
- Credentials come from the real environment or a `.env` in the cwd (or next to the
  script); real env vars win over `.env`.
- `uv` recommended — the inline PEP 723 header auto-installs `requests` + `paho-mqtt`.

## Run

```bash
# upload + publish a pending post message
uv run scripts/tiktok_publish.py ./tiktok_output/x.png --idea "a cat in red boots" --caption "morning vibes"

# upload only, no HiveMQ publish
uv run scripts/tiktok_publish.py ./x.png --no-hivemq --folder /tiktok
```

Without `uv`: `pip install requests paho-mqtt` then `python3 scripts/tiktok_publish.py ...`.

## Flags

- `image` (positional) — local image file to upload.
- `--folder PATH` — ImageKit destination folder (default `/tiktok`).
- `--idea TEXT` — post `Idea` field (primary).
- `--caption TEXT`, `--description TEXT` — post `Caption` / `Description`.
- `--profile NAME` — post `Profile` field.
- `--account HANDLE` — post `Account` field (e.g. `@captgani`); default is
  `TIKTOK_ACCOUNT` env var, else omitted. The agent switches to this account
  before posting.
- `--status VALUE` — post `Status` field (default `pending`).
- `--unique` — let ImageKit append a random suffix to the file name. Off by
  default so the file keeps its exact name (e.g. `tiktok_YYYYMMDD_HHMMSS.png` from
  the `tiktok-image` skill, which is already unique). Turning this on can produce
  names like `name_-Ab12.png`.
- `--no-hivemq` — upload to ImageKit only; skip the HiveMQ publish.
- `--json` — print the full result JSON.

## Output & errors

Default output: the public ImageKit URL, and the HiveMQ topic when the publish
succeeds. `ImageURL`, `ImageKitFileId`, and `ImagePath` are filled from the upload
automatically — `ImagePath` is the **actual name ImageKit stored the file under**
(matches `ImageURL`), so with the default (no `--unique`) it stays the clean
`tiktok_YYYYMMDD_HHMMSS.png` produced by `tiktok-image`. Only non-empty fields are
sent. Exits non-zero if the ImageKit upload fails, or if the HiveMQ publish was
requested but failed.
