#!/usr/bin/env python3
"""
Trending Topic Recommender for TikTok Content Pipeline.

Fetches Google Trends data for a given industry/persona, filters the most
relevant topics, then returns 2-4 curated recommendations as JSON.

Usage (CLI):
    uv run trending-recommender --industry automotive --persona gani --json
    uv run trending-recommender --industry automotive --count 4

Usage (as module):
    from trending_recommender import recommend_topics
    topics = recommend_topics(industry="automotive", persona_keywords=["mobil", "motor"])
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import random
import urllib.error
import urllib.request
from typing import Optional

# ── pytrends ──────────────────────────────────────────────────────────────────
try:
    from pytrends.request import TrendReq
except ImportError:
    print("pytrends not installed. Run: uv add pytrends", file=sys.stderr)
    sys.exit(1)


# ── Constants ─────────────────────────────────────────────────────────────────

TOKENROUTER_BASE_URL = "https://api.tokenrouter.com/v1"
DEFAULT_LLM_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_COUNT = 4

# Geo code: Indonesia
GEO = "ID"

# Industry keyword seeds — expanded per industry so pytrends has richer signal
INDUSTRY_SEEDS: dict[str, list[str]] = {
    "automotive": [
        "mobil klasik", "motor jadul", "vespa", "restorasi mobil", "otomotif indonesia",
        "motor custom", "bebek restorasi", "mobil antik",
    ],
    "skincare": [
        "skincare murah", "skincare lokal", "rutinitas skincare", "skincare apotek",
        "sunscreen", "serum wajah", "skincare pemula",
    ],
    "fashion": [
        "outfit kekinian", "fashion lokal", "thrift fashion", "outfit ootd",
        "baju murah", "fashion hijab",
    ],
    "food": [
        "resep masakan", "makanan viral", "street food indonesia", "kuliner lokal",
        "jajanan murah", "makanan trending",
    ],
    "finance": [
        "investasi pemula", "nabung saham", "kripto indonesia", "finansial tips",
        "cuan 2025", "tips keuangan",
    ],
}

# Fallback keywords if industry not in INDUSTRY_SEEDS
FALLBACK_SEEDS = ["trending indonesia", "viral tiktok", "konten viral"]

# Gani's persona keywords for relevance filtering
PERSONA_KEYWORDS_BY_PROFILE: dict[str, list[str]] = {
    "gani": [
        "mobil", "motor", "vespa", "restorasi", "klasik", "bengkel", "otomotif",
        "vintage", "kustom", "custom", "antik", "jadul", "modifikasi", "sparepart",
        "mesin", "petrolhead", "rally", "drift", "touring",
    ],
    "kalila": [
        "skincare", "kulit", "wajah", "serum", "sunscreen", "moisturizer",
        "toner", "essence", "lokal", "apotek", "murah", "review", "cleanser",
        "spf", "acne", "jerawat", "routine",
    ],
}


class TrendingError(Exception):
    """Raised when trending fetch or LLM recommendation fails."""


def _get_api_key() -> str:
    key = os.getenv("TOKENROUTER_API_KEY")
    if not key:
        raise TrendingError(
            "TOKENROUTER_API_KEY env var is not set. "
            "Export it before running the recommender."
        )
    return key


# ── Google Trends fetch ────────────────────────────────────────────────────────

def _fetch_trending_searches(geo: str = GEO) -> list[str]:
    """Fetch today's trending searches from Google Trends for a given geo.
    Falls back to empty list if the endpoint returns 404 (deprecated for some geos)."""
    try:
        pt = TrendReq(hl="id-ID", tz=420, timeout=(10, 30))
        df = pt.trending_searches(pn=geo.lower())
        return df[0].tolist()
    except Exception:
        # trending_searches endpoint is deprecated/404 for many geos — not fatal
        return []


def _fetch_related_queries(seeds: list[str], geo: str = GEO) -> list[str]:
    """Fetch rising related queries for seed keywords."""
    results: list[str] = []
    pt = TrendReq(hl="id-ID", tz=420, timeout=(10, 30))
    
    # Process in batches of max 5 (pytrends limit)
    for i in range(0, len(seeds), 5):
        batch = seeds[i:i+5]
        try:
            pt.build_payload(batch, cat=0, timeframe="now 7-d", geo=geo)
            time.sleep(random.uniform(1.5, 3.0))  # rate limit friendly
            related = pt.related_queries()
            for kw in batch:
                if kw in related and related[kw].get("rising") is not None:
                    rising_df = related[kw]["rising"]
                    if rising_df is not None and len(rising_df) > 0:
                        results.extend(rising_df["query"].head(5).tolist())
        except Exception:
            continue  # skip failed batches gracefully

    return results


def _fetch_interest_over_time(seeds: list[str], geo: str = GEO) -> dict[str, int]:
    """Fetch average interest score for seed keywords over past 7 days."""
    scores: dict[str, int] = {}
    pt = TrendReq(hl="id-ID", tz=420, timeout=(10, 30))

    for i in range(0, len(seeds), 5):
        batch = seeds[i:i+5]
        try:
            pt.build_payload(batch, cat=0, timeframe="now 7-d", geo=geo)
            time.sleep(random.uniform(1.0, 2.0))
            df = pt.interest_over_time()
            if df is not None and not df.empty:
                for kw in batch:
                    if kw in df.columns:
                        scores[kw] = int(df[kw].mean())
        except Exception:
            continue

    return scores


# ── LLM-based curation ────────────────────────────────────────────────────────

def _ask_llm_for_topics(
    trending: list[str],
    related: list[str],
    interest_scores: dict[str, int],
    industry: str,
    persona: Optional[str],
    count: int,
    model: str,
    timeout: int = 60,
) -> list[dict]:
    """
    Use LLM to curate the most TikTok-worthy topics from trending data.
    Returns a list of {topic, why, angle} dicts (count items).
    """

    # Build context for LLM
    trending_str = "\n".join(f"- {t}" for t in trending[:30])
    related_str = "\n".join(f"- {r}" for r in related[:30]) if related else "(none)"
    scores_str = "\n".join(
        f"- {k}: score {v}" for k, v in
        sorted(interest_scores.items(), key=lambda x: x[1], reverse=True)[:15]
    ) if interest_scores else "(no score data)"

    persona_context = ""
    if persona:
        profile_kws = PERSONA_KEYWORDS_BY_PROFILE.get(persona.lower(), [])
        if profile_kws:
            persona_context = f"\nCreator persona: {persona}. Niche keywords: {', '.join(profile_kws[:10])}."

    system = (
        "You are a TikTok content strategist. Given trending data from Google Trends "
        f"(Indonesia, {industry} industry), pick the {count} most TikTok-worthy topics "
        f"for a short-form video creator in the {industry} niche.{persona_context}\n\n"
        "Rules:\n"
        "- Topics must be relevant to the creator's niche/persona\n"
        "- Topics should have high engagement potential on TikTok Indonesia\n"
        "- Prefer topics with a personal/emotional angle (story, nostalgia, opinion)\n"
        "- Avoid generic or low-resonance topics\n\n"
        f"Return ONLY a JSON array of exactly {count} objects, each with:\n"
        '  "topic": short Indonesian topic title (max 10 words)\n'
        '  "why": one sentence why this topic is trending and relevant\n'
        '  "angle": one sentence content angle/hook idea for TikTok\n'
        "No markdown, no extra text — just the JSON array."
    )

    user = (
        f"=== Google Trends: Trending Searches (Indonesia, today) ===\n{trending_str}\n\n"
        f"=== Related Rising Queries (past 7 days) ===\n{related_str}\n\n"
        f"=== Interest Scores for {industry} seed keywords ===\n{scores_str}"
    )

    payload = {
        "model": model,
        "max_tokens": 1000,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{TOKENROUTER_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise TrendingError(f"HTTP {e.code} from TokenRouter: {err_body}") from e
    except urllib.error.URLError as e:
        raise TrendingError(f"Network error: {e}") from e

    if "error" in resp:
        raise TrendingError(f"API error: {resp['error']}")

    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise TrendingError(f"Unexpected response shape: {e}") from e

    # Parse JSON array
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.startswith("json"):
            s = s[4:].strip()
    start, end = s.find("["), s.rfind("]")
    if start != -1 and end != -1:
        s = s[start:end+1]

    try:
        topics = json.loads(s)
    except json.JSONDecodeError as e:
        raise TrendingError(f"Could not parse topics JSON: {e}; got: {content[:300]!r}")

    if not isinstance(topics, list) or len(topics) == 0:
        raise TrendingError(f"Expected a non-empty JSON array of topics, got: {content[:200]!r}")

    return topics[:count]


# ── Public API ────────────────────────────────────────────────────────────────

def recommend_topics(
    industry: str = "automotive",
    persona: Optional[str] = None,
    count: int = DEFAULT_COUNT,
    geo: str = GEO,
    model: str = DEFAULT_LLM_MODEL,
    verbose: bool = False,
) -> list[dict]:
    """
    Fetch trending data and return count recommended topics for the given industry.

    Returns list of {topic, why, angle} dicts.
    """
    seeds = INDUSTRY_SEEDS.get(industry.lower(), FALLBACK_SEEDS)

    if verbose:
        print(f"[trending] Fetching trending searches for {geo}...", file=sys.stderr)
    trending = _fetch_trending_searches(geo=geo)
    if verbose:
        print(f"[trending] Got {len(trending)} trending searches", file=sys.stderr)
        print(f"[trending] Fetching related queries for seeds: {seeds[:3]}...", file=sys.stderr)

    related = _fetch_related_queries(seeds, geo=geo)
    if verbose:
        print(f"[trending] Got {len(related)} related rising queries", file=sys.stderr)
        print(f"[trending] Fetching interest scores...", file=sys.stderr)

    interest_scores = _fetch_interest_over_time(seeds, geo=geo)
    if verbose:
        print(f"[trending] Got interest scores for {len(interest_scores)} keywords", file=sys.stderr)
        print(f"[trending] Asking LLM to curate {count} topics...", file=sys.stderr)

    topics = _ask_llm_for_topics(
        trending=trending,
        related=related,
        interest_scores=interest_scores,
        industry=industry,
        persona=persona,
        count=count,
        model=model,
    )
    return topics


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch Google Trends and recommend 2-4 TikTok topics for a given industry/persona."
    )
    parser.add_argument("--industry", "-i", default="automotive",
                        choices=list(INDUSTRY_SEEDS.keys()),
                        help=f"Industry niche (default: automotive)")
    parser.add_argument("--persona", "-p", default=None,
                        help="Persona profile name (e.g. gani, kalila) for relevance filtering")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_COUNT,
                        help=f"Number of topic recommendations (default: {DEFAULT_COUNT})")
    parser.add_argument("--geo", default=GEO,
                        help=f"Google Trends geo code (default: {GEO})")
    parser.add_argument("--model", default=DEFAULT_LLM_MODEL,
                        help=f"TokenRouter model (default: {DEFAULT_LLM_MODEL})")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON array")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print progress to stderr")
    args = parser.parse_args()

    try:
        topics = recommend_topics(
            industry=args.industry,
            persona=args.persona,
            count=args.count,
            geo=args.geo,
            model=args.model,
            verbose=args.verbose,
        )
    except TrendingError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(topics, indent=2, ensure_ascii=False))
    else:
        print(f"\n🔥 Top {len(topics)} Trending Topics — {args.industry.title()} | Indonesia\n")
        for i, t in enumerate(topics, 1):
            print(f"{i}. {t.get('topic', '?')}")
            print(f"   Why: {t.get('why', '')}")
            print(f"   Angle: {t.get('angle', '')}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
