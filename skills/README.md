# TikTok pipeline — Agent Skills

The individual stages of this repo's TikTok content pipeline, repackaged as standalone
[Agent Skills](https://agentskills.io) so other AI agents can install and run them.
Each skill is a self-contained folder (`SKILL.md` + a `scripts/` bundle that includes
every module it imports), so a skill works on its own without the rest of the repo.

## Install

With the [`npx skills`](https://github.com/vercel-labs/skills) tool, from this repo
(`<owner>/<repo>` = your GitHub `owner/repo`):

```bash
npx skills add <owner>/tiktok-pipeline/skills/tiktok-image      # one capability
npx skills add <owner>/tiktok-pipeline/skills/tiktok-content    # another
npx skills add <owner>/tiktok-pipeline/skills/tiktok-reply-comment  # read-then-reply loop
```

Or install from a local checkout: `npx skills add ./skills/tiktok-image`. Installed
skills land in `~/.claude/skills/<name>/` (personal) or `.claude/skills/<name>/`
(project).

## Skills

| Skill | What it does | Required env |
|---|---|---|
| [`tiktok-content`](tiktok-content/SKILL.md) | From a topic → `{image_prompt, caption, description, hashtags}` | `TOKENROUTER_API_KEY` |
| [`tiktok-image`](tiktok-image/SKILL.md) | Render a 9:16 1080x1920 image to a local PNG (multi-angle `--ref`) | `TOKENROUTER_API_KEY` |
| [`tiktok-publish`](tiktok-publish/SKILL.md) | Publish an image to TikTok: upload to ImageKit + publish a pending post to HiveMQ | `IMAGEKIT_PRIVATE_KEY`, `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD` |
| [`tiktok-comment`](tiktok-comment/SKILL.md) | Comment on an existing post: AI-write a comment from a sentiment (or take exact text) + publish to the `tiktok/comments` topic. Also supports one-off replies (`--reply-to-author`) and the `Account` field (`--account`). | `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD`, `TOKENROUTER_API_KEY` (generate only) |
| [`tiktok-reply-comment`](tiktok-reply-comment/SKILL.md) | Read-then-reply loop: scrape a post's comments via the downstream reader, AI-write a short reply to each, and publish them with `ReplyTo` set. State file dedups so re-runs don't spam. | `HIVEMQ_HOST`, `HIVEMQ_USERNAME`, `HIVEMQ_PASSWORD`, `TOKENROUTER_API_KEY`, optional `TIKTOK_ACCOUNT` |

The skills are independent: install only the capabilities you need. A common chain
is `tiktok-content` (image prompt + caption + hashtags) → `tiktok-image` (render the
PNG from that prompt) → `tiktok-publish` (upload + queue it for TikTok).
`tiktok-comment` and `tiktok-reply-comment` are standalone tools for engaging with
existing posts — the former for one-off top-level comments or one-off replies, the
latter for batch-replying to a post's comments.

## Runtime

Each skill's entry script carries a [PEP 723](https://peps.python.org/pep-0723/)
inline-metadata header declaring its dependencies, so the recommended way to run it
is with [`uv`](https://docs.astral.sh/uv/) — deps install automatically into an
ephemeral environment:

```bash
uv run scripts/<entry>.py <args>
```

Without `uv`, install the deps yourself and use `python3` (see each `SKILL.md`):

```bash
pip install requests pillow        # whichever the skill needs
python3 scripts/<entry>.py <args>
```

Credentials are read from real environment variables or a `.env` file in the current
working directory (real env vars take precedence). See each skill's `SKILL.md` for the
exact variables and flags.

## Maintenance

The skill `scripts/` bundles are **generated** from the canonical modules at the repo
root — the root modules are the single source of truth. After changing a root module,
regenerate the copies (and re-apply the PEP 723 headers) with:

```bash
bash skills/sync.sh
```

`SKILL.md` and this README are hand-maintained and are not touched by `sync.sh`.
