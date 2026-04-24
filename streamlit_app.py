#!/usr/bin/env python3
"""
@noah.haupt Instagram Dashboard — Streamlit
Growth-focused: 30-day trend is the hero metric, not all-time totals.

Local:  streamlit run streamlit_app.py
Cloud:  deploy to Streamlit Community Cloud; set METRICS_GITHUB_TOKEN +
        METRICS_GITHUB_REPO in Streamlit secrets so the nightly sync can
        push metrics.json to the repo.
"""

import json, os, base64
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import streamlit as st
import plotly.graph_objects as go
import requests as rq

from claude_insights import (
    insight_snapshot, insight_make_more, insight_avoid,
    insight_format, insight_growth,
    composite_score, cohort_max,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="@noah.haupt: IG Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constants ─────────────────────────────────────────────────────────────────
# Pillar values come from Notion IG Reels Tracker → "Pillar" select field.
# sync_pillars_from_notion.py writes them into metrics.json as `pillar`.
# "Other" is the fallback bucket for reels with no Pillar set in Notion.
FORMAT_ORDER  = [
    "Coaching-Call-Type",
    "Green-Screen-Type",
    "Discord-QA",
    "Discord-Ideas",
    "Talking-Head",
    "Podcast-Type",
    "Long-Form-Clip-Type",
    "Other",
]
FORMAT_COLORS = {
    "Coaching-Call-Type":  "#fb923c",   # orange
    "Green-Screen-Type":   "#fbbf24",   # yellow
    "Discord-QA":          "#60a5fa",   # blue
    "Talking-Head":        "#cbd5e1",   # light gray (default in Notion)
    "Podcast-Type":        "#4ade80",   # green
    "Long-Form-Clip-Type": "#f87171",   # red
    "Uncategorized":       "#6b7280",   # gray
}

def pillar_label(name: str) -> str:
    """Display label for a Notion Pillar value: strip '-Type' suffix and replace dashes with spaces.
    Examples: 'Green-Screen-Type' -> 'Green Screen', 'Coaching-Call-Type' -> 'Coaching Call',
              'Talking-Head' -> 'Talking Head', 'Discord-QA' -> 'Discord QA'."""
    if not name:
        return "Uncategorized"
    return name.replace("-Type", "").replace("-", " ")

def hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# ── CSS injection ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stApp"],
[data-testid="stApp"] *, [data-testid="stMarkdownContainer"] *,
.stMarkdown, .stMarkdown *,
button, input, textarea, select, span, div, p, h1, h2, h3, h4, h5, h6, td, th, a {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}

#MainMenu, footer, header { visibility: hidden; }
.stApp { background: #07070b !important; }
.block-container { padding: 28px 36px 48px !important; max-width: 1580px !important; }

/* Kill scrollbars on every Streamlit wrapper that might clip a chart */
[data-testid="stElementContainer"],
[data-testid="stPlotlyChart"],
[data-testid="stVerticalBlock"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="column"],
.element-container,
.stElementContainer,
.stPlotlyChart,
.js-plotly-plot,
.plot-container,
.svg-container,
.user-select-none {
    overflow: visible !important;
    overflow-x: visible !important;
    overflow-y: visible !important;
}

/* Plotly chart containers — styled as cards */
[data-testid="stPlotlyChart"] {
    background: #0d0d14;
    border: 1px solid rgba(255,255,255,0.075);
    border-radius: 16px;
    padding: 18px 20px 14px;
}
[data-testid="stPlotlyChart"] > div { border-radius: 0; }

/* Section headers — actual visible headings */
.nh-sec {
    font-size: 22px; font-weight: 800; color: #f2f2fa;
    letter-spacing: -0.6px;
    margin: 32px 0 14px;
    padding: 0 0 0 14px;
    border-left: 4px solid #a78bfa;
    line-height: 1.2;
}
.nh-sec .nh-sec-sub {
    display: block;
    font-size: 11px; font-weight: 600; color: #6e6e88;
    text-transform: uppercase; letter-spacing: 1.4px;
    margin-top: 4px;
}
/* Smaller variant: chart axis labels etc. */
.nh-sec.chart-lbl {
    font-size: 10.5px; font-weight: 700; color: #525268;
    text-transform: uppercase; letter-spacing: 1.5px;
    margin: 0 0 8px;
    padding-left: 2px;
    border-left: none;
}

/* Hero cards */
.hero-card {
    background: #0d0d14;
    border: 1px solid rgba(255,255,255,0.075);
    border-radius: 16px;
    padding: 20px 22px 18px;
    min-height: 118px;
}
.hero-card.hl {
    background: linear-gradient(140deg,rgba(96,165,250,0.14),rgba(96,165,250,0.03));
    border-color: rgba(96,165,250,0.25);
}
.hero-lbl  { font-size: 13px; font-weight: 500; color: #9898aa; margin-bottom: 10px; }
.hero-val  { font-size: 38px; font-weight: 800; letter-spacing: -1.8px; color: #f2f2fa; line-height: 1; }
.hero-val.bl { color: #60a5fa; }
.hero-val.gr { color: #4ade80; }
.hero-val.pu { color: #a78bfa; }
.hero-val.am { color: #fbbf24; }
.hero-delta {
    font-size: 12px; font-weight: 500; margin-top: 9px; color: #555568;
}
.up   { color: #4ade80; font-weight: 700; }
.dn   { color: #f87171; font-weight: 700; }
.flat { color: #555568; }

/* Context stat cards */
.ctx-card {
    background: #0d0d14; border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px; padding: 16px 18px 14px; min-height: 86px;
}
.ctx-lbl { font-size: 11.5px; font-weight: 500; color: #7a7a95; margin-bottom: 7px; }
.ctx-val { font-size: 26px; font-weight: 800; letter-spacing: -0.8px; color: #d8d8e6; line-height: 1; }
.ctx-sub { font-size: 11px; color: #444458; margin-top: 5px; font-weight: 500; }

/* Chart wrapper cards */
.chart-card {
    background: #0d0d14; border: 1px solid rgba(255,255,255,0.075);
    border-radius: 16px; padding: 20px 20px 14px;
}
.chart-card .nh-sec { margin-bottom: 10px; }

/* Make st.container(border=True) look like .chart-card (used for Content Mix) */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #0d0d14 !important;
    border: 1px solid rgba(255,255,255,0.075) !important;
    border-radius: 16px !important;
    padding: 20px 20px 14px !important;
}

/* Comparison rows */
.cmp-wrap { display: flex; flex-direction: column; gap: 0; }
.cmp-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.035);
}
.cmp-row:last-child { border-bottom: none; }
.cmp-lbl { font-size: 12px; color: #888899; font-weight: 500; }
.cmp-right { display: flex; align-items: center; gap: 8px; }
.cmp-prev  { font-size: 12px; color: #3a3a52; font-weight: 600; }
.cmp-arr   { font-size: 11px; color: #303048; }
.cmp-curr  { font-size: 13px; font-weight: 700; }
.cmp-delta {
    font-size: 10px; font-weight: 700; padding: 2px 7px;
    border-radius: 5px; background: rgba(255,255,255,0.05);
}

/* Goal bars */
.goal-row { margin-bottom: 16px; }
.goal-row:last-child { margin-bottom: 0; }
.goal-top  { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.goal-lbl  { font-size: 12px; color: #888899; font-weight: 500; }
.goal-vv   { font-size: 12px; font-weight: 700; }
.goal-tgt  { color: #383850; font-weight: 500; }
.goal-bg   { height: 5px; background: rgba(255,255,255,0.07); border-radius: 5px; overflow: hidden; }
.goal-fill { height: 100%; border-radius: 5px; }

/* Best performer cards */
.perf-card {
    background: rgba(255,255,255,0.022);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px; padding: 18px 20px; height: 100%;
}
.perf-thumb {
    width: 100%; height: 88px; object-fit: cover;
    border-radius: 8px; margin-bottom: 12px; opacity: 0.82; display: block;
}
.perf-lbl { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.1px; margin-bottom: 8px; }
.perf-cap { font-size: 12.5px; color: #888899; line-height: 1.45; margin-bottom: 9px; }
.perf-tag { margin-bottom: 11px; }
.tag {
    display: inline-block; font-size: 10px; font-weight: 600;
    padding: 3px 9px; border-radius: 5px; white-space: nowrap;
}
.perf-stats { display: flex; gap: 15px; flex-wrap: wrap; }
.perf-m { font-size: 10px; color: #5c5c78; line-height: 1.8; font-weight: 500; }
.perf-m span { font-size: 18px; font-weight: 800; display: block; color: #eaeaf8; letter-spacing: -0.5px; }

/* Divider */
.nh-div { height: 1px; background: rgba(255,255,255,0.04); margin: 22px 0; }

/* Claude insight line — sits above each section */
.nh-insight {
    background: linear-gradient(135deg, rgba(167,139,250,0.07), rgba(96,165,250,0.04));
    border: 1px solid rgba(167,139,250,0.18);
    border-left: 3px solid #a78bfa;
    border-radius: 12px;
    padding: 13px 18px;
    margin: 0 0 14px;
    font-size: 13.5px;
    color: #c8c8e0;
    line-height: 1.5;
    font-weight: 500;
}
.nh-insight.empty {
    background: rgba(255,255,255,0.02);
    border: 1px dashed rgba(255,255,255,0.08);
    border-left: 3px dashed rgba(255,255,255,0.15);
    color: #45455a;
    font-style: italic;
}
.nh-insight-label {
    display: inline-block;
    font-size: 9.5px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: #a78bfa;
    margin-right: 8px;
    vertical-align: 2px;
}

/* Reel card grid — 3 cards per row */
.reel-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-bottom: 10px;
}
@media (max-width: 1200px) { .reel-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 720px)  { .reel-grid { grid-template-columns: 1fr; } }

.reel-card {
    display: grid;
    grid-template-columns: 38% 62%;
    gap: 10px;
    background: #0d0d14;
    border: 1px solid rgba(255,255,255,0.075);
    border-radius: 14px;
    padding: 10px;
    align-items: stretch;
}
.reel-card.win    { border-left: 3px solid #4ade80; }
.reel-card.lose   { border-left: 3px solid #f87171; }
.reel-card.recent { border-left: 3px solid #60a5fa; }

.reel-thumb-wrap {
    width: 100%;
    aspect-ratio: 9 / 14;
    border-radius: 8px;
    overflow: hidden;
    background: #1a1a24;
    position: relative;
}
.reel-thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}
.reel-body {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 10px;
    flex: 1;
}
.reel-head { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.reel-cap {
    font-size: 12.5px;
    color: #d8d8e6;
    font-weight: 500;
    line-height: 1.4;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
}
.reel-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.reel-date { font-size: 11px; color: #555568; font-variant-numeric: tabular-nums; white-space: nowrap; }
.reel-link { font-size: 11px; color: #60a5fa; text-decoration: none; font-weight: 600; white-space: nowrap; }
.reel-link:hover { text-decoration: underline; }

/* Pill-style stats — each metric is a chip */
.reel-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: auto;
    padding-top: 10px;
    border-top: 1px solid rgba(255,255,255,0.05);
}
.reel-stat {
    display: inline-flex; align-items: baseline; gap: 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 999px;
    padding: 6px 13px;
    font-size: 11px; color: #8a8aa0; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.6px;
    white-space: nowrap;
}
.reel-stat b {
    font-size: 16px; font-weight: 800; color: #eaeaf8;
    letter-spacing: -0.2px; font-variant-numeric: tabular-nums;
    text-transform: none;
}
.reel-stat.vw { background: rgba(96,165,250,0.10); border-color: rgba(96,165,250,0.22); }
.reel-stat.vw b { color: #60a5fa; }
.reel-stat.sv { background: rgba(74,222,128,0.10); border-color: rgba(74,222,128,0.22); }
.reel-stat.sv b { color: #4ade80; }
.reel-stat.sh { background: rgba(167,139,250,0.10); border-color: rgba(167,139,250,0.22); }
.reel-stat.sh b { color: #a78bfa; }
.reel-stat.cm { background: rgba(249,168,212,0.10); border-color: rgba(249,168,212,0.22); }
.reel-stat.cm b { color: #f9a8d4; }
.reel-stat.cr { background: rgba(251,191,36,0.10); border-color: rgba(251,191,36,0.22); }
.reel-stat.cr b { color: #fbbf24; }

/* All-reels table */
.nh-tbl-wrap {
    background: #0d0d14;
    border: 1px solid rgba(255,255,255,0.075);
    border-radius: 16px;
    padding: 4px 6px;
    max-height: 520px;
    overflow-y: auto;
}
.nh-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.nh-tbl thead th {
    position: sticky; top: 0; background: #0d0d14;
    color: #3a3a52; text-transform: uppercase; letter-spacing: 1.2px;
    font-size: 10px; font-weight: 700; text-align: left;
    padding: 14px 14px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.nh-tbl tbody td {
    padding: 11px 14px; color: #aaa8c0; font-weight: 500;
    vertical-align: middle;
    border: none !important;
    border-bottom: 1px solid rgba(255,255,255,0.025) !important;
}
.nh-tbl tbody tr:last-child td { border-bottom: none !important; }
.nh-tbl tbody tr:hover td { background: rgba(255,255,255,0.022); }
.nh-tbl td.num { text-align: right; font-variant-numeric: tabular-nums; color: #d8d8e6; font-weight: 600; }
.nh-tbl td.dt  { color: #6e6e88; font-variant-numeric: tabular-nums; white-space: nowrap; }
.nh-tbl td.cap { color: #c8c8d8; max-width: 460px; }
.nh-tbl td a   { color: #60a5fa; text-decoration: none; font-weight: 600; }
.nh-tbl td a:hover { text-decoration: underline; }
.nh-tbl .tag-sm {
    display: inline-block; font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 4px; white-space: nowrap;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(n):
    n = int(n)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 10_000:    return f"{n/1_000:.1f}K"
    if n >= 1_000:     return f"{n:,}"
    return str(n)

def trunc(s, n=65):
    s = (s or "").replace("\n", " ").strip()
    return (s[:n] + "…") if len(s) > n else s

def reel_date(r):
    try:
        return datetime.fromisoformat(r["date"]).date()
    except Exception:
        return datetime.now(timezone.utc).date()

def detect_format(caption: str) -> str:
    c = (caption or "").lower()
    if any(w in c for w in ["discord", "asked my ai", "trained an ai", "ai chatbot", "my ai"]):
        return "Discord AI"
    if any(w in c for w in ["my client", "my student", "went from $", "went from 0",
                              "i was at $", "scaled from", "he made", "she made",
                              "they made", "closed a", "signed a client", "0 to $",
                              "my first $", "i was losing", "i scaled"]):
        return "Social Proof"
    if any(w in c for w in ["how to", "easiest way to", "fastest way to", "tips",
                              "the best way", "watch this if", "cheat code",
                              "truth about", "system i use", "the secret to",
                              "watch this to", "way to book", "way to get",
                              "step by step", "way to sign"]):
        return "Tutorial"
    if any(w in c for w in ["stop", "if you", "you need", "you are", "you have",
                              "your agency", "you're", "you used", "you want",
                              "you obsess", "you idolize", "most people", "nobody tells",
                              "the problem with", "this is why"]):
        return "Talking Head"
    return "Other"

def delta_html(curr, prev, suffix=" vs prev 30d"):
    """Returns HTML for the trend delta shown under hero values."""
    if prev == 0:
        return f'<span class="flat">First period: no comparison yet</span>'
    pct = (curr - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    cls  = "up" if pct >= 0 else "dn"
    arr  = "▲" if pct >= 0 else "▼"
    return f'{arr} <span class="{cls}">{sign}{pct:.0f}%</span>{suffix}'


def render_insight(text: str, label: str = "INSIGHT"):
    """Render Claude-generated insight line above a section. Empty text = empty placeholder."""
    if text:
        clean = text.replace("**", "").replace("__", "")
        st.markdown(
            f'<div class="nh-insight">'
            f'<span class="nh-insight-label">{label}</span>'
            f'{clean}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="nh-insight empty">'
            f'<span class="nh-insight-label" style="color:#3a3a4e">{label}</span>'
            f'Set ANTHROPIC_API_KEY to surface AI insights here.</div>',
            unsafe_allow_html=True,
        )


def reel_row_card(reel: dict, variant: str = "recent") -> str:
    """HTML for a reel card: thumbnail on the LEFT half, caption/meta/stats on the RIGHT.
    Cards wrap inside a .reel-grid container so they render 2 per row.
    variant: 'win' (green), 'lose' (red), 'recent' (blue)."""
    cap   = trunc(reel.get("caption", "") or reel.get("shortcode", ""), 160).replace('"', "'")
    thumb = reel.get("thumbnail", "")
    link  = reel.get("permalink", "")
    fname = reel.get("format", "Uncategorized")
    fc    = FORMAT_COLORS.get(fname, "#9ca3af")
    flbl  = pillar_label(fname)
    date  = reel.get("date", "")[:10]
    cr    = reel.get("completion_rate", 0) or 0
    sv    = reel.get("saves", 0)
    sh    = reel.get("shares", 0)
    vw    = reel.get("views", 0)
    cm    = reel.get("comments", 0) or 0
    thumb_html = (
        f'<img src="{thumb}" class="reel-thumb" onerror="this.parentElement.innerHTML=\'\'">'
        if thumb else ''
    )
    link_html = f'<a class="reel-link" href="{link}" target="_blank">Open ↗</a>' if link else ""
    badge_html = (
        f'<span class="tag" style="background:{fc}22;color:{fc};border:1px solid {fc}44;'
        f'font-size:10px;padding:2px 8px;border-radius:5px;font-weight:600">{flbl}</span>'
    )
    return (
        f'<div class="reel-card {variant}">'
        f'  <div class="reel-thumb-wrap">{thumb_html}</div>'
        f'  <div class="reel-body">'
        f'    <div class="reel-head">'
        f'      <div class="reel-meta">{badge_html}<span class="reel-date">{date}</span>{link_html}</div>'
        f'      <div class="reel-cap">{cap}</div>'
        f'    </div>'
        f'    <div class="reel-stats">'
        f'      <span class="reel-stat vw"><b>{vw:,}</b>Views</span>'
        f'      <span class="reel-stat sv"><b>{sv}</b>Saves</span>'
        f'      <span class="reel-stat sh"><b>{sh}</b>Sends</span>'
        f'      <span class="reel-stat cm"><b>{cm}</b>Comments</span>'
        f'      <span class="reel-stat cr"><b>{cr:.0f}%</b>Completion</span>'
        f'    </div>'
        f'  </div>'
        f'</div>'
    )


@st.cache_data(ttl=21600)  # 6h cache — Claude calls only fire when data changes
def cached_insight(fn_name: str, payload_str: str) -> str:
    """Wrapper to cache Claude calls by function + payload hash."""
    from claude_insights import (
        insight_snapshot as _i_snap,
        insight_make_more as _i_mm,
        insight_avoid as _i_av,
        insight_format as _i_fmt,
        insight_growth as _i_gr,
    )
    fn_map = {
        "snapshot":  _i_snap,
        "make_more": _i_mm,
        "avoid":     _i_av,
        "format":    _i_fmt,
        "growth":    _i_gr,
    }
    fn = fn_map.get(fn_name)
    if not fn:
        return ""
    payload = json.loads(payload_str)
    return fn(payload)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data():
    """
    Load metrics.json. On Streamlit Cloud, the sync script pushes the file to
    this repo via GitHub API so it's always up to date.
    """
    candidates = [
        Path(__file__).parent / "metrics.json",
        Path("metrics.json"),
    ]
    for c in candidates:
        if c.exists():
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


# ── Plotly layout helper ──────────────────────────────────────────────────────

def apply_style(fig, height=220, show_legend=True, legend_right=False):
    lp = dict(orientation="h", font=dict(color="#6b6b85", size=11),
              bgcolor="rgba(0,0,0,0)", x=0.5, xanchor="center", y=-0.22, yanchor="top")
    if legend_right:
        lp.update(orientation="v", x=1.02, y=0.5, xanchor="left", yanchor="middle")
    bottom_margin = 30 if (not show_legend or legend_right) else 90
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        font=dict(family="Inter, system-ui, sans-serif", color="#505068", size=11),
        margin=dict(l=8, r=8, t=12, b=bottom_margin),
        legend=lp if show_legend else dict(visible=False),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            zerolinecolor="rgba(0,0,0,0)",
            tickfont=dict(color="#505068", size=10),
            linecolor="rgba(0,0,0,0)",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            zerolinecolor="rgba(0,0,0,0)",
            tickfont=dict(color="#505068", size=10),
            linecolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor="#16161e",
            bordercolor="rgba(255,255,255,0.12)",
            font=dict(family="Inter, system-ui, sans-serif", color="#eaeaf8", size=13),
        ),
    )
    return fig


# ── Main ──────────────────────────────────────────────────────────────────────

data = load_data()

if data is None:
    st.error("metrics.json not found. Run sync_ig_metrics.py first, then refresh.")
    st.stop()

reels = data.get("reels", [])
if not reels:
    st.error("No reels in metrics.json. Run the sync and refresh.")
    st.stop()

# Filter out pre-collab reels (Noah-solo content before Arman started April 3, 2026).
# Keeps dashboard focused on the work we're actually accountable for.
COLLAB_START = "2026-04-03"
reels = [r for r in reels if r.get("date", "") >= COLLAB_START]

# Pillar (from Notion) is the ONLY source of truth for categorization.
# Blank Pillar = Uncategorized. The made-up detect_format keyword classifier
# is intentionally ignored. Noah-solo uploads get auto-tagged Talking-Head
# by push_to_notion when their orphan row is created.
for r in reels:
    p = r.get("pillar")
    r["format"] = p if p else "Uncategorized"

# ── Account data ──────────────────────────────────────────────────────────────
profile  = data.get("account_profile", {})
insights = data.get("account_insights", {})
synced   = data.get("last_sync", "")[:19].replace("T", " ") + " UTC"

followers = profile.get("followers", 0)
following = profile.get("following", 0)

today   = datetime.now(timezone.utc).date()
d30_ago = today - timedelta(days=30)
d60_ago = today - timedelta(days=60)

fc_history    = insights.get("follower_count", {}).get("history", [])
reach_history = insights.get("reach",          {}).get("history", [])

new_followers_30d = sum(
    d["value"] for d in fc_history if d.get("date", "") >= str(d30_ago)
)
new_followers_prev30 = sum(
    d["value"] for d in fc_history
    if str(d60_ago) <= d.get("date", "") < str(d30_ago)
)
account_reach_30d = sum(
    d["value"] for d in reach_history if d.get("date", "") >= str(d30_ago)
)

# ── Reel periods ──────────────────────────────────────────────────────────────
recent = [r for r in reels if reel_date(r) >= d30_ago]
prev30 = [r for r in reels if d60_ago <= reel_date(r) < d30_ago]

def agg(rs):
    if not rs:
        return dict(views=0, saves=0, shares=0, likes=0, follows=0,
                    count=0, avg_save_rate=0, avg_views=0)
    views  = sum(r["views"]  for r in rs)
    saves  = sum(r["saves"]  for r in rs)
    shares = sum(r["shares"] for r in rs)
    likes  = sum(r["likes"]  for r in rs)
    follows= sum(r.get("follows", 0) for r in rs)
    count  = len(rs)
    return dict(
        views=views, saves=saves, shares=shares,
        likes=likes, follows=follows, count=count,
        avg_save_rate=round(sum(r["save_rate"] for r in rs) / count, 2),
        avg_views=round(views / count),
    )

curr = agg(recent)
prev = agg(prev30)
all_ = agg(reels)

# All-time
total_reels  = len(reels)
viral_reels  = sum(1 for r in reels if r["views"] >= 5_000)
avg_save_r   = round(sum(r["save_rate"] for r in reels) / total_reels, 2) if total_reels else 0

# ── Monthly trend ─────────────────────────────────────────────────────────────
monthly = defaultdict(lambda: {"views": 0, "saves": 0, "shares": 0, "count": 0})
for r in reels:
    m = r["date"][:7]
    monthly[m]["views"]  += r["views"]
    monthly[m]["saves"]  += r["saves"]
    monthly[m]["shares"] += r["shares"]
    monthly[m]["count"]  += 1

months_sorted = sorted(monthly.keys())

def month_lbl(ym):
    y, m = ym.split("-")
    mn = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][int(m)]
    return f"{mn} '{y[2:]}"

trend_labels  = [month_lbl(m) for m in months_sorted]
trend_views   = [monthly[m]["views"]  for m in months_sorted]
trend_saves   = [monthly[m]["saves"]  for m in months_sorted]
trend_shares  = [monthly[m]["shares"] for m in months_sorted]

# ── Format data ───────────────────────────────────────────────────────────────
fmt_data = defaultdict(lambda: {"views": 0, "saves": 0, "count": 0})
for r in reels:
    f = r["format"]
    fmt_data[f]["views"] += r["views"]
    fmt_data[f]["saves"] += r["saves"]
    fmt_data[f]["count"] += 1

# ── Follower growth (daily, last 60d) ─────────────────────────────────────────
d60 = today - timedelta(days=60)
fc_recent = [d for d in fc_history if d.get("date", "") >= str(d60)]
fc_dates  = [d["date"][5:] for d in fc_recent]   # MM-DD
fc_values = [d["value"] for d in fc_recent]

# ── Best performers (kept for All-Reels table sort) ─────────────────────────
by_views = sorted(reels, key=lambda r: r["views"], reverse=True)

# ── Composite score: 0.4×saves + 0.3×shares + 0.3×completion_rate ────────────
# Normalized across the current cohort. Reels without completion_rate still
# score — just get 0 weight on that axis.
_cmax = cohort_max(reels)
for r in reels:
    r["_score"] = composite_score(r, _cmax)

scored_reels = sorted(reels, key=lambda r: r["_score"], reverse=True)
top_5    = scored_reels[:5]
bottom_3 = [r for r in scored_reels[-3:] if r["_score"] > 0][::-1]  # worst-first

# Last 7 posted reels (by date desc)
last_7 = sorted(reels, key=lambda r: r.get("date", ""), reverse=True)[:7]


# ── Layout ────────────────────────────────────────────────────────────────────

# Header
hc1, hc2 = st.columns([3, 1])
with hc1:
    st.markdown("""
    <div style="padding-top:2px">
      <div style="font-size:22px;font-weight:900;letter-spacing:-0.8px;color:#f2f2fa;line-height:1.1">@noah.haupt</div>
      <div style="font-size:13px;color:#555568;font-weight:500;margin-top:4px">Instagram Performance Overview</div>
    </div>
    """, unsafe_allow_html=True)
with hc2:
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px">
      <span style="display:inline-block;background:#0d0d14;border:1px solid rgba(255,255,255,0.075);border-radius:10px;padding:9px 18px;font-size:12px;color:#555568;font-weight:500">
        Last sync &nbsp;<b style="color:#4ade80;font-weight:700">{synced}</b>
      </span>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div class="nh-div"></div>', unsafe_allow_html=True)

# ── Section 1: Growth Snapshot ────────────────────────────────────────────────
st.markdown('<div class="nh-sec">Growth Snapshot: Last 30 Days</div>', unsafe_allow_html=True)

snapshot_payload = {
    "followers_total": followers,
    "new_followers_this_30d": new_followers_30d,
    "new_followers_prev_30d": new_followers_prev30,
    "account_reach_30d": account_reach_30d,
    "reels_posted_this_30d": curr["count"],
    "reels_posted_prev_30d": prev["count"],
    "views_this_30d": curr["views"],
    "views_prev_30d": prev["views"],
    "saves_this_30d": curr["saves"],
    "saves_prev_30d": prev["saves"],
    "avg_save_rate_this_30d": curr["avg_save_rate"],
    "avg_save_rate_prev_30d": prev["avg_save_rate"],
}
render_insight(cached_insight("snapshot", json.dumps(snapshot_payload)))

h1, h2, h3, h4, h5 = st.columns(5)
with h1:
    st.markdown(f"""
    <div class="hero-card hl">
      <div class="hero-lbl">Followers</div>
      <div class="hero-val bl">{followers:,}</div>
      <div class="hero-delta"><span style="color:#4ade80">+{new_followers_30d} in 30d</span> &middot; {delta_html(new_followers_30d, new_followers_prev30)}</div>
    </div>
    """, unsafe_allow_html=True)
with h2:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Reel Views (30d)</div>
      <div class="hero-val">{fmt(curr["views"])}</div>
      <div class="hero-delta">{delta_html(curr["views"], prev["views"])}</div>
    </div>
    """, unsafe_allow_html=True)
with h3:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Saves (30d)</div>
      <div class="hero-val gr">{fmt(curr["saves"])}</div>
      <div class="hero-delta">{delta_html(curr["saves"], prev["saves"])}</div>
    </div>
    """, unsafe_allow_html=True)
with h4:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Avg Save Rate (30d)</div>
      <div class="hero-val pu">{curr["avg_save_rate"]}%</div>
      <div class="hero-delta">{delta_html(curr["avg_save_rate"], prev["avg_save_rate"])}</div>
    </div>
    """, unsafe_allow_html=True)
with h5:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Reels Posted (30d)</div>
      <div class="hero-val am">{curr["count"]}</div>
      <div class="hero-delta">{delta_html(curr["count"], prev["count"])}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 2: Make More Like This ────────────────────────────────────────────
st.markdown('<div class="nh-sec">Make More Like This: Top 5 by Composite Score</div>', unsafe_allow_html=True)

if top_5:
    mm_payload = [
        {
            "caption": (r.get("caption") or "")[:140],
            "format": pillar_label(r.get("format", "Uncategorized")),
            "saves": r.get("saves", 0),
            "shares": r.get("shares", 0),
            "completion_rate": r.get("completion_rate", 0),
            "duration_sec": r.get("duration_sec", 0),
        } for r in top_5
    ]
    render_insight(cached_insight("make_more", json.dumps(mm_payload)), label="PATTERN")

    rows_html = "".join(reel_row_card(r, "win") for r in top_5)
    st.markdown(f'<div class="reel-grid">{rows_html}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#555568;font-size:13px;padding:20px 0">Not enough data yet.</div>',
                unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 3: Avoid ──────────────────────────────────────────────────────────
st.markdown('<div class="nh-sec">Avoid: Bottom 3 by Composite Score</div>', unsafe_allow_html=True)

if bottom_3:
    av_payload = [
        {
            "caption": (r.get("caption") or "")[:140],
            "format": pillar_label(r.get("format", "Uncategorized")),
            "saves": r.get("saves", 0),
            "shares": r.get("shares", 0),
            "completion_rate": r.get("completion_rate", 0),
            "duration_sec": r.get("duration_sec", 0),
        } for r in bottom_3
    ]
    render_insight(cached_insight("avoid", json.dumps(av_payload)), label="FAILURE PATTERN")

    rows_html = "".join(reel_row_card(r, "lose") for r in bottom_3)
    st.markdown(f'<div class="reel-grid">{rows_html}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#555568;font-size:13px;padding:20px 0">Not enough data yet.</div>',
                unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 4: Format Performance ─────────────────────────────────────────────
st.markdown('<div class="nh-sec">Format Performance</div>', unsafe_allow_html=True)

fmt_stats_for_claude = []
for f in FORMAT_ORDER:
    d = fmt_data.get(f)
    if d and d["count"] > 0:
        reels_in_fmt = [r for r in reels if r["format"] == f]
        avg_cr = round(
            sum(r.get("completion_rate", 0) or 0 for r in reels_in_fmt) / len(reels_in_fmt), 1
        ) if reels_in_fmt else 0
        fmt_stats_for_claude.append({
            "format": f,
            "reel_count": d["count"],
            "avg_views": round(d["views"] / d["count"]),
            "avg_saves": round(d["saves"] / d["count"], 1),
            "avg_completion_rate": avg_cr,
        })

fmt_stats_for_claude_clean = [
    {**s, "format": pillar_label(s["format"])} for s in fmt_stats_for_claude
]
render_insight(cached_insight("format", json.dumps(fmt_stats_for_claude_clean)), label="FORMAT TAKE")

st.markdown('<div class="nh-sec chart-lbl">Avg Views + Saves by Format</div>', unsafe_allow_html=True)
fmt_labels_list = [pillar_label(s["format"]) for s in fmt_stats_for_claude]
fmt_avg_views   = [s["avg_views"] for s in fmt_stats_for_claude]
fmt_avg_saves   = [s["avg_saves"] for s in fmt_stats_for_claude]
fmt_bar_colors  = [FORMAT_COLORS.get(s["format"], "#9ca3af") for s in fmt_stats_for_claude]

fig3 = go.Figure()
fig3.add_trace(go.Bar(
    y=fmt_labels_list, x=fmt_avg_views, name="Avg Views",
    orientation="h",
    marker=dict(color=[hex_rgba(c, 0.82) for c in fmt_bar_colors]),
    hovertemplate="%{y}: %{x:,} avg views<extra></extra>",
))
fig3.add_trace(go.Bar(
    y=fmt_labels_list, x=fmt_avg_saves, name="Avg Saves",
    orientation="h",
    marker=dict(color=[hex_rgba(c, 0.33) for c in fmt_bar_colors]),
    hovertemplate="%{y}: %{x} avg saves<extra></extra>",
))
apply_style(fig3, height=320)
fig3.update_layout(
    barmode="overlay",
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)", tickfont=dict(color="#505068", size=10)),
    yaxis=dict(tickfont=dict(color="#9898aa", size=11), gridcolor="rgba(0,0,0,0)"),
)
st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 5: Weekly Growth ──────────────────────────────────────────────────
st.markdown('<div class="nh-sec">Weekly Growth</div>', unsafe_allow_html=True)

weekly_followers = fc_values[-28:] if len(fc_values) >= 28 else fc_values
weekly_avg_cr = []
for wk_start in range(28, 0, -7):
    wk_end = wk_start - 7
    wk_reels = [
        r for r in reels
        if r.get("completion_rate", 0)
        and (today - timedelta(days=wk_start)) <= reel_date(r) < (today - timedelta(days=wk_end))
    ]
    if wk_reels:
        weekly_avg_cr.append(round(
            sum(r["completion_rate"] for r in wk_reels) / len(wk_reels), 1
        ))
    else:
        weekly_avg_cr.append(0)

growth_payload = {
    "followers_daily_last_60d": fc_values[-60:],
    "new_followers_this_30d": new_followers_30d,
    "new_followers_prev_30d": new_followers_prev30,
    "weekly_avg_completion_rate_oldest_to_newest": weekly_avg_cr,
}
render_insight(cached_insight("growth", json.dumps(growth_payload)), label="MOMENTUM")

wg1, wg2 = st.columns(2)
with wg1:
    st.markdown('<div class="nh-sec chart-lbl">New Followers per Day (60d)</div>', unsafe_allow_html=True)
    fig2 = go.Figure(go.Bar(
        x=fc_dates, y=fc_values,
        marker=dict(color="rgba(74,222,128,0.5)", line=dict(color="#4ade80", width=0)),
        hovertemplate="%{x}: +%{y}<extra></extra>",
    ))
    apply_style(fig2, height=300, show_legend=False)
    fig2.update_layout(xaxis=dict(
        type="category", tickfont=dict(color="#505068", size=9), nticks=10,
    ))
    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

with wg2:
    st.markdown('<div class="nh-sec chart-lbl">Avg Completion Rate by Week</div>', unsafe_allow_html=True)
    wk_labels = [f"W-{i+1}" for i in range(len(weekly_avg_cr))][::-1]
    fig_cr = go.Figure(go.Scatter(
        x=wk_labels, y=weekly_avg_cr,
        mode="lines+markers",
        line=dict(color="#fbbf24", width=2),
        fill="tozeroy", fillcolor="rgba(251,191,36,0.08)",
        marker=dict(size=6, color="#fbbf24"),
        hovertemplate="%{x}: %{y}%<extra></extra>",
    ))
    apply_style(fig_cr, height=300, show_legend=False)
    fig_cr.update_layout(
        yaxis=dict(ticksuffix="%", tickfont=dict(color="#505068", size=10)),
    )
    st.plotly_chart(fig_cr, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 6: Last 7 Days Posted ─────────────────────────────────────────────
st.markdown('<div class="nh-sec">Last 7 Reels Posted: Proof of Work</div>', unsafe_allow_html=True)

if last_7:
    rows_html = "".join(reel_row_card(r, "recent") for r in last_7)
    st.markdown(f'<div class="reel-grid">{rows_html}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#555568;font-size:13px;padding:20px 0">No recent reels.</div>',
                unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 7: All Reels Table ────────────────────────────────────────────────
st.markdown('<div class="nh-sec">All Reels</div>', unsafe_allow_html=True)

def reel_row_html(r):
    cap   = trunc(r.get("caption", "") or r.get("shortcode", ""), 75).replace("<", "&lt;")
    fname = r.get("format", "Uncategorized")
    fc    = FORMAT_COLORS.get(fname, "#9ca3af")
    flbl  = pillar_label(fname)
    link  = r.get("permalink", "")
    link_html = f'<a href="{link}" target="_blank">Open ↗</a>' if link else ""
    cr    = r.get("completion_rate", 0) or 0
    cr_str = f'{cr:.0f}%' if cr else '-'
    return (
        f"<tr>"
        f'<td class="dt">{r["date"]}</td>'
        f'<td class="cap">{cap}</td>'
        f'<td><span class="tag-sm" style="background:{fc}22;color:{fc};border:1px solid {fc}44">{flbl}</span></td>'
        f'<td class="num">{r["views"]:,}</td>'
        f'<td class="num">{r["saves"]:,}</td>'
        f'<td class="num">{r["shares"]:,}</td>'
        f'<td class="num">{cr_str}</td>'
        f'<td class="num">{r["save_rate"]:.2f}%</td>'
        f'<td>{link_html}</td>'
        f"</tr>"
    )

# Default sort by composite score (best first), so the table mirrors Make More ordering
table_reels = sorted(reels, key=lambda r: r["_score"], reverse=True)

table_html = (
    '<div class="nh-tbl-wrap"><table class="nh-tbl">'
    '<thead><tr>'
    '<th>Date</th><th>Caption</th><th>Format</th>'
    '<th style="text-align:right">Views</th>'
    '<th style="text-align:right">Saves</th>'
    '<th style="text-align:right">Sends</th>'
    '<th style="text-align:right">Compl. %</th>'
    '<th style="text-align:right">Save %</th>'
    '<th>Link</th>'
    '</tr></thead><tbody>'
    + "".join(reel_row_html(r) for r in table_reels)
    + '</tbody></table></div>'
)
st.markdown(table_html, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#2a2a3a;font-size:11px;padding-top:18px;font-weight:500">
  {total_reels} reels &middot; @noah.haupt &middot; synced {synced}
</div>
""", unsafe_allow_html=True)
