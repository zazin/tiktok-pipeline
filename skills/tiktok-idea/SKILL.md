---
name: tiktok-idea
description: Invent a one-line TikTok image idea with an Anthropic model served over TokenRouter. Use when an agent needs a fresh, viral-style image concept — optionally steered by a theme, or shaped by a recurring-character persona/profile. Requires TOKENROUTER_API_KEY.
---

# TikTok Idea Generator

Generates a single one-line image idea suitable for a 9:16 TikTok post. With a
`--profile`, it loads that character's persona + variety pools (outfit / setting /
pose) and describes a scene for them; a `--seed` makes the pick reproducible.

## Requirements

- `TOKENROUTER_API_KEY` — read from the real environment or a `.env` file in the
  current working directory (or next to the script). Real env vars win over `.env`.
- `uv` installed (recommended). The script declares its deps inline (PEP 723) — it
  is stdlib-only, so no packages are installed.

## Run

```bash
uv run scripts/idea_generator.py --theme "cyberpunk street food"
```

Prints the bare idea string to stdout. Without `uv`:

```bash
python3 scripts/idea_generator.py --theme "cyberpunk street food"
```

## Flags

- `--theme TEXT` — optional theme to steer the idea.
- `--model ID` — TokenRouter Anthropic model id (default `anthropic/claude-haiku-4.5`).
- `--profile NAME` — use a profile's persona + variety pools (scene-focused prompt).
- `--seed N` — deterministic outfit/setting/pose pick (reproducible ideas).

## Profiles

`--profile NAME` loads `profiles/<NAME>/profile.json` relative to the cwd. See the
profile schema in the `tiktok-pipeline` or `tiktok-profile` skill. You supply your
own profiles directory; none ships with this skill.

## Output & errors

stdout: one line (the idea). Exits non-zero with a message on `stderr` if
`TOKENROUTER_API_KEY` is missing, the API call fails, or the response is empty.
