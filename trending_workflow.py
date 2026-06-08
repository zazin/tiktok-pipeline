#!/usr/bin/env python3
"""
Trending Workflow Orchestrator.

Step 1: Fetch trending topics for a given industry/persona and present to user.
Step 2: Accept user's topic selection(s), then run content+image generation for each.

Usage (Step 1 — fetch & present topics):
    uv run trending-workflow --industry automotive --persona gani

Usage (Step 2 — generate content+image for selected topics by index or name):
    uv run trending-workflow --generate "1,3"        # by index (comma-separated)
    uv run trending-workflow --generate "all"         # all recommended topics

The script uses a state file (~/.tiktok-trending-state.json) to persist
recommendations between steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

STATE_FILE = Path.home() / ".tiktok-trending-state.json"
SCRIPT_DIR = Path(__file__).parent


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _fetch_topics(
    industry: str,
    persona: Optional[str],
    count: int,
    verbose: bool = False,
) -> list[dict]:
    """Run trending-recommender and return the list of topic dicts."""
    cmd = [
        "uv", "run", "trending-recommender",
        "--industry", industry,
        "--count", str(count),
        "--json",
    ]
    if persona:
        cmd += ["--persona", persona]
    if verbose:
        cmd += ["--verbose"]

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR)
    )
    if verbose and result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"trending-recommender failed:\n{result.stderr}")

    # Parse only JSON from stdout (skip any warning lines)
    output = result.stdout.strip()
    start = output.find("[")
    end = output.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"No JSON array in trending-recommender output:\n{output}")
    return json.loads(output[start:end+1])


def _profile_flag(persona: Optional[str]) -> list[str]:
    """Build --profile flag if persona is set."""
    if persona:
        return ["--profile", persona]
    return []


def _generate_for_topic(
    topic_title: str,
    persona: Optional[str],
    verbose: bool = False,
) -> dict:
    """
    Run: tiktok-content → tiktok-generate for a single topic.
    Returns dict with {topic, image_path, caption, description, hashtags} or {error}.
    """
    # Step A: Generate content package
    content_cmd = [
        "uv", "run", "tiktok-content",
        topic_title,
        "--json",
    ]
    if persona:
        # Build persona string from profile
        profile_map = {
            "gani": (
                "Gani Captgani (@captgani), Pria Gen X 40 tahun. "
                "The Nostalgic Petrolhead Boss & Skena Roda Dua. "
                "Fokus: mobil 90-an/modern classic, Vespa dua tak, bebek restorasi, motor kustom. "
                "Gaya: ceplas-ceplos, metafora tongkrongan, Jakarta urban tempo dulu."
            ),
            "kalila": (
                "Lika Kalila (@likaliku.skin), wanita Gen Z 22 tahun, Beauty & Skincare. "
                "First-jobber skincare creator, anti-filter realist, fokus produk lokal/apotek <Rp120k."
            ),
        }
        persona_str = profile_map.get(persona.lower(), persona)
        content_cmd += ["--persona", persona_str]

    if verbose:
        print(f"  [content] Generating for: {topic_title!r}...", file=sys.stderr)

    cr = subprocess.run(content_cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
    if cr.returncode != 0:
        return {"topic": topic_title, "error": f"content generation failed: {cr.stderr[:200]}"}

    try:
        content = json.loads(cr.stdout.strip())
    except json.JSONDecodeError:
        return {"topic": topic_title, "error": f"could not parse content JSON: {cr.stdout[:200]}"}

    image_prompt = content.get("image_prompt", "")
    if not image_prompt:
        return {"topic": topic_title, "error": "empty image_prompt from content generator"}

    # Step B: Generate image
    avatar_refs: dict[str, list[str]] = {
        "gani": [
            "https://ik.imagekit.io/salt/profiles/gani/gani_01.jpeg?updatedAt=1780874901272",
            "https://ik.imagekit.io/salt/profiles/gani/ganii_02.jpeg?updatedAt=1780874901475",
            "https://ik.imagekit.io/salt/profiles/gani/gani_03.jpeg?updatedAt=1780874901475",
        ],
        "kalila": [
            "https://ik.imagekit.io/salt/profiles/kalila/02.jpeg?updatedAt=1780626852158",
            "https://ik.imagekit.io/salt/profiles/kalila/05.jpeg?updatedAt=1780626857363",
        ],
    }

    image_cmd = ["uv", "run", "tiktok-generate", image_prompt]
    refs = avatar_refs.get(persona.lower(), []) if persona else []
    for ref_url in refs:
        image_cmd += ["--ref", ref_url]
    if refs:
        image_cmd += ["--ref-kind", "preserve"]

    if verbose:
        print(f"  [image] Rendering image for: {topic_title!r}...", file=sys.stderr)

    ir = subprocess.run(image_cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
    if ir.returncode != 0:
        return {
            "topic": topic_title,
            "error": f"image generation failed: {ir.stderr[:300]}",
            "content": content,
        }

    # Parse "Saved: <path>" from output
    saved_path = None
    for line in ir.stdout.splitlines():
        if line.startswith("Saved:"):
            saved_path = line.split("Saved:", 1)[1].strip()
            break

    return {
        "topic": topic_title,
        "image_path": saved_path,
        "image_prompt": image_prompt,
        "caption": content.get("caption", ""),
        "description": content.get("description", ""),
        "hashtags": content.get("hashtags", []),
    }


def _format_recommendations(topics: list[dict], industry: str) -> str:
    lines = [f"🔥 *Trending Topics — {industry.title()} Indonesia*\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"*{i}. {t.get('topic', '?')}*")
        lines.append(f"   📈 {t.get('why', '')}")
        lines.append(f"   💡 _{t.get('angle', '')}_")
        lines.append("")
    lines.append("Reply dengan nomor topik yang mau di-generate (contoh: `1` atau `1,3` atau `all`)")
    return "\n".join(lines)


def _parse_selection(selection: str, total: int) -> list[int]:
    """Parse user selection into 0-based indices."""
    s = selection.strip().lower()
    if s == "all":
        return list(range(total))
    indices = []
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1  # convert to 0-based
            if 0 <= idx < total:
                indices.append(idx)
    return sorted(set(indices))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="2-step trending workflow: fetch topics → user picks → generate images."
    )
    parser.add_argument("--industry", "-i", default="automotive",
                        choices=["automotive", "skincare", "fashion", "food", "finance"],
                        help="Industry niche")
    parser.add_argument("--persona", "-p", default=None,
                        help="Persona profile (gani, kalila)")
    parser.add_argument("--count", "-n", type=int, default=4,
                        help="Number of topic recommendations (default: 4)")
    parser.add_argument("--generate", "-g", default=None,
                        help="Step 2: topic selection (e.g. '1', '1,3', 'all'). Uses saved state.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    # ── STEP 2: Generate images for selected topics ──────────────────────────
    if args.generate is not None:
        state = _load_state()
        topics = state.get("topics")
        if not topics:
            print("❌ No saved topic recommendations found. Run Step 1 first (without --generate).", file=sys.stderr)
            return 1

        persona = state.get("persona")
        industry = state.get("industry", "automotive")
        indices = _parse_selection(args.generate, len(topics))

        if not indices:
            print(f"❌ Invalid selection: {args.generate!r}. Use numbers 1-{len(topics)} or 'all'.", file=sys.stderr)
            return 1

        selected = [topics[i] for i in indices]
        print(f"\n🎬 Generating content+image for {len(selected)} topic(s)...\n")

        results = []
        for t in selected:
            topic_title = t.get("topic", "")
            print(f"⏳ Processing: {topic_title}")
            result = _generate_for_topic(topic_title, persona, verbose=args.verbose)
            results.append(result)

            if "error" in result:
                print(f"  ❌ Error: {result['error']}")
            else:
                print(f"  ✅ Image: {result.get('image_path', '?')}")
                print(f"  📝 Caption: {result.get('caption', '')}")
                print(f"  🏷️  {' '.join(result.get('hashtags', []))}")
            print()

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))

        # Clear state after generation
        _save_state({})
        return 0

    # ── STEP 1: Fetch and display recommendations ────────────────────────────
    print(f"🔍 Fetching trending topics for {args.industry} (Indonesia)...", file=sys.stderr)
    try:
        topics = _fetch_topics(
            industry=args.industry,
            persona=args.persona,
            count=args.count,
            verbose=args.verbose,
        )
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    # Save state for Step 2
    _save_state({
        "industry": args.industry,
        "persona": args.persona,
        "topics": topics,
    })

    if args.json:
        print(json.dumps(topics, indent=2, ensure_ascii=False))
    else:
        print(_format_recommendations(topics, args.industry))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
