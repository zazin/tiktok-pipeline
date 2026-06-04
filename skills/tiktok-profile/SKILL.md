---
name: tiktok-profile
description: Load and inspect a recurring-character profile (persona + reference images + variety pools) from a profiles/<name>/profile.json directory. Use when an agent needs to list available characters or resolve a profile's persona and reference image paths before generating ideas/images. No API keys required.
---

# TikTok Profile Loader

Reads `profiles/<name>/profile.json`, validates it, resolves and verifies the
listed reference image paths, and composes the effective `persona` string (base
persona folded together with demographics + content pillars). Used by the
`tiktok-idea` and `tiktok-pipeline` skills to drive a consistent character.

## Requirements

- No API keys. Stdlib-only (no packages installed). `uv` recommended for a clean run.
- A profiles directory you provide (none ships with this skill). See
  [refs/PROFILE_SCHEMA.md](refs/PROFILE_SCHEMA.md) for the `profile.json` schema and a
  template.

## Run

```bash
uv run scripts/profile_loader.py --list --profiles-dir ./profiles
uv run scripts/profile_loader.py kalila --profiles-dir ./profiles
```

Without `uv`: `python3 scripts/profile_loader.py --list`.

## Flags

- `name` (positional, optional) — profile to show (resolved persona + reference paths).
- `--list` — list available profiles (those with a `profile.json`).
- `--profiles-dir DIR` — profiles root (default `profiles/`).

## Output & errors

Shows the profile's resolved fields (name, persona, reference paths, reference kind,
variety). Exits non-zero if the profile, its `profile.json`, or a referenced image is
missing.
