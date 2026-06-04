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
npx skills add <owner>/tiktok-pipeline/skills/tiktok-idea       # another
```

Or install from a local checkout: `npx skills add ./skills/tiktok-image`. Installed
skills land in `~/.claude/skills/<name>/` (personal) or `.claude/skills/<name>/`
(project).

## Skills

| Skill | What it does | Required env |
|---|---|---|
| [`tiktok-idea`](tiktok-idea/SKILL.md) | Invent a one-line TikTok image idea | `TOKENROUTER_API_KEY` |
| [`tiktok-caption`](tiktok-caption/SKILL.md) | Write `{caption, description}` for a concept | `TOKENROUTER_API_KEY` |
| [`tiktok-image`](tiktok-image/SKILL.md) | Render a 9:16 1080x1920 image (+ optional upload) | `TOKENROUTER_API_KEY` (`IMAGEKIT_PRIVATE_KEY` if `--upload`) |
| [`imagekit-upload`](imagekit-upload/SKILL.md) | Upload local images → public ImageKit URLs | `IMAGEKIT_PRIVATE_KEY` |
| [`airtable-log`](airtable-log/SKILL.md) | Write one post record to Airtable | `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME` |
| [`airtable-migrate`](airtable-migrate/SKILL.md) | Create/extend the Airtable Posts schema (run once) | `AIRTABLE_API_KEY` (schema scopes), `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME` |
| [`tiktok-profile`](tiktok-profile/SKILL.md) | Load a recurring-character profile | _(none)_ |

The skills are independent: install only the capabilities you need.

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

`SKILL.md`, this README, and `refs/PROFILE_SCHEMA.md` are hand-maintained and are not
touched by `sync.sh`.
