#!/usr/bin/env bash
#
# Regenerate the scripts/ bundle inside every skill from the canonical modules
# at the repo root. The root modules are the single source of truth; the copies
# under skills/<name>/scripts/ are GENERATED — do not hand-edit them.
#
# For each skill we copy its entry module plus every sibling it imports, then
# prepend a PEP 723 inline-metadata header to the ENTRY copy only (uv reads the
# header from the invoked file; imported siblings ignore it), so that
#     uv run skills/<name>/scripts/<entry>.py ...
# auto-installs the right deps into an ephemeral environment.
#
# Usage:  bash skills/sync.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS="$ROOT/skills"

# Prepend a PEP 723 header to a copied entry script.
#   $1 = path to the entry .py copy
#   $2 = TOML contents of the dependencies array (e.g. '"requests>=2.31"'), may be empty
inject_header() {
  local file="$1" deps="$2" tmp
  tmp="$file.tmp"
  awk -v deps="$deps" '
    NR==1 && /^#!/ {
      print
      print "# /// script"
      print "# requires-python = \">=3.10\""
      print "# dependencies = [" deps "]"
      print "# ///"
      next
    }
    NR==1 {
      print "# /// script"
      print "# requires-python = \">=3.10\""
      print "# dependencies = [" deps "]"
      print "# ///"
      print
      next
    }
    { print }
  ' "$file" > "$tmp" && mv "$tmp" "$file"
}

# Build one skill bundle.
#   $1 = skill name (folder)
#   $2 = entry module (without .py)
#   $3 = space-separated module list to copy (without .py; must include the entry)
#   $4 = PEP 723 dependencies array contents (may be empty)
build() {
  local name="$1" entry="$2" mods="$3" deps="$4"
  local dir="$SKILLS/$name/scripts" m
  rm -rf "$dir"
  mkdir -p "$dir"
  for m in $mods; do
    cp "$ROOT/$m.py" "$dir/$m.py"
  done
  inject_header "$dir/$entry.py" "$deps"
  echo "  built $name  (entry: $entry.py)"
}

echo "Regenerating skill script bundles from $ROOT ..."

build tiktok-caption   caption_generator      "caption_generator env_loader"                                                                              ""
build tiktok-image     tiktok_image_generator "tiktok_image_generator imagekit_uploader airtable_logger env_loader"                                       '"pillow>=10.0", "requests>=2.31"'

echo "Done. (SKILL.md / README.md are hand-maintained and not touched by this script.)"
