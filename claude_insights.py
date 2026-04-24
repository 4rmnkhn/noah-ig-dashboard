#!/usr/bin/env python3
"""
Claude-powered dashboard insights.

Each function takes a slice of reel data and returns a 1-2 sentence plain-English
insight to render above its dashboard section. Falls back to "" if no API key.

Cached for 6h via streamlit's @st.cache_data wrapper applied at call site.

Cost: ~$0.001 per dashboard load (Sonnet 4.6, ~500 input tokens, ~50 output).
"""

import os
import json
from typing import Optional

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

_client = None


def _get_client():
    """Lazy-init Anthropic client. Returns None if no key or SDK missing."""
    global _client
    if _client is not None:
        return _client
    if not ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "anthropic", "-q"])
        from anthropic import Anthropic
    _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _ask(system: str, user: str, max_tokens: int = 200) -> str:
    """Single-turn call. Returns empty string on any failure."""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return ""


# ── Section-specific insight generators ───────────────────────────────────────

VOICE = (
    "You write 1-2 sentence dashboard insights for a content creator. "
    "Plain English, direct, no hedging. No emojis, no exclamation marks. "
    "Lead with the observation, then the implication. "
    "Numbers must come from the data given. "
    "Banned: 'looks like', 'it seems', 'consider', 'might want to', 'try to'. "
    "Use indicative voice: 'X is doing Y. Do Z.' "
    "No markdown formatting (no **bold**, no _italics_, no headings, no bullets). Plain prose only."
)


def insight_snapshot(account: dict) -> str:
    """Account-level snapshot: followers delta, reach delta, posting cadence."""
    payload = json.dumps(account, indent=2)
    user = (
        "This is a creator's account snapshot for the last 30 days vs the previous 30. "
        "Write ONE sentence (max 2) about what's actually happening at the account level. "
        "Compare the two periods. If reach is flat but followers grew, name that. If posting "
        "cadence dropped, name that. No fluff.\n\n"
        f"Data:\n{payload}"
    )
    return _ask(VOICE, user, max_tokens=120)


def insight_make_more(top_reels: list) -> str:
    """The pattern shared across the top-performing reels."""
    slim = [
        {
            "caption": (r.get("caption") or "")[:140],
            "format": r.get("format"),
            "saves": r.get("saves"),
            "shares": r.get("shares"),
            "completion_rate": r.get("completion_rate"),
            "duration_sec": r.get("duration_sec"),
        }
        for r in top_reels
    ]
    payload = json.dumps(slim, indent=2)
    user = (
        "These are a creator's top 5 performing reels by composite score (saves + shares + "
        "completion). Find the SHARED PATTERN — what hook style, format, length, or topic "
        "they have in common that drove performance. Be specific (cite numbers). Then give "
        "a one-line directive: 'Make more X.' Total: 1-2 sentences.\n\n"
        f"Reels:\n{payload}"
    )
    return _ask(VOICE, user, max_tokens=180)


def insight_avoid(bottom_reels: list) -> str:
    """The pattern shared across the worst-performing reels."""
    slim = [
        {
            "caption": (r.get("caption") or "")[:140],
            "format": r.get("format"),
            "saves": r.get("saves"),
            "shares": r.get("shares"),
            "completion_rate": r.get("completion_rate"),
            "duration_sec": r.get("duration_sec"),
        }
        for r in bottom_reels
    ]
    payload = json.dumps(slim, indent=2)
    user = (
        "These are a creator's 3 worst-performing reels by composite score. Find the SHARED "
        "FAILURE PATTERN — what they have in common that killed performance (length, hook "
        "style, topic, format). Be specific (cite numbers). Then give a one-line directive: "
        "'Stop X.' or 'Avoid Y.' Total: 1-2 sentences. Don't be punitive — diagnostic.\n\n"
        f"Reels:\n{payload}"
    )
    return _ask(VOICE, user, max_tokens=180)


def insight_format(format_stats: list) -> str:
    """Which format is winning, which is dragging."""
    payload = json.dumps(format_stats, indent=2)
    user = (
        "These are per-format averages for a creator's reels. Identify the strongest and "
        "weakest format by avg saves + avg completion_rate. One sentence diagnosis, one "
        "sentence directive ('Shift mix toward X, less Y').\n\n"
        f"Format stats:\n{payload}"
    )
    return _ask(VOICE, user, max_tokens=180)


def insight_growth(growth: dict) -> str:
    """Account momentum: accelerating, plateauing, or declining."""
    payload = json.dumps(growth, indent=2)
    user = (
        "This is account growth data over recent weeks. Diagnose momentum in one sentence "
        "('accelerating', 'plateauing', 'declining' — and by how much). Then one sentence "
        "implication.\n\n"
        f"Growth:\n{payload}"
    )
    return _ask(VOICE, user, max_tokens=140)


# ── Composite score helper ────────────────────────────────────────────────────

def composite_score(reel: dict, cohort_max: dict) -> float:
    """Score a reel relative to its cohort. Returns 0-1.
    Weights: saves 0.4, shares 0.3, completion_rate 0.3."""
    def _norm(v, m):
        return (v or 0) / m if m else 0
    return (
        0.4 * _norm(reel.get("saves", 0),           cohort_max.get("saves", 1))   +
        0.3 * _norm(reel.get("shares", 0),          cohort_max.get("shares", 1))  +
        0.3 * _norm(reel.get("completion_rate", 0), cohort_max.get("completion_rate", 1))
    )


def cohort_max(reels: list) -> dict:
    """Return per-metric max across cohort, used to normalize composite score."""
    return {
        "saves":           max((r.get("saves", 0)           for r in reels), default=1) or 1,
        "shares":          max((r.get("shares", 0)          for r in reels), default=1) or 1,
        "completion_rate": max((r.get("completion_rate", 0) for r in reels), default=1) or 1,
    }
