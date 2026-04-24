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

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="@noah.haupt — IG Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constants ─────────────────────────────────────────────────────────────────
FORMAT_ORDER  = ["Discord AI", "Social Proof", "Tutorial", "Talking Head", "Other"]
FORMAT_COLORS = {
    "Discord AI":   "#a78bfa",
    "Social Proof": "#4ade80",
    "Tutorial":     "#60a5fa",
    "Talking Head": "#fbbf24",
    "Other":        "#9ca3af",
}

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

/* Section headers */
.nh-sec {
    font-size: 10.5px; font-weight: 700; color: #525268;
    text-transform: uppercase; letter-spacing: 1.5px;
    margin: 0 0 8px;
}
/* Section label that sits directly above a chart card — pulled in tight */
.nh-sec.chart-lbl {
    margin: 0 0 8px;
    padding-left: 2px;
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
        return f'<span class="flat">First period — no comparison yet</span>'
    pct = (curr - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    cls  = "up" if pct >= 0 else "dn"
    arr  = "▲" if pct >= 0 else "▼"
    return f'{arr} <span class="{cls}">{sign}{pct:.0f}%</span>{suffix}'


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

# Ensure format is set on every reel
for r in reels:
    if not r.get("format"):
        r["format"] = detect_format(r.get("caption", ""))

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

# ── Trajectory goals ──────────────────────────────────────────────────────────
goal_monthly_views     = max(round(curr["views"] * 1.25 / 1000) * 1000, 10_000)
goal_monthly_followers = max(round(new_followers_30d * 1.3 / 10) * 10, 50)
goal_avg_save_rate     = round(max(avg_save_r * 1.5, avg_save_r + 0.3), 1)
goal_5k_reels          = max(viral_reels + 1, 2)

def pct_toward(val, goal):
    return min(round((val / goal) * 100), 100) if goal else 0

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

# ── Best performers ───────────────────────────────────────────────────────────
by_views = sorted(reels, key=lambda r: r["views"],     reverse=True)
by_saver = sorted(reels, key=lambda r: r["save_rate"], reverse=True)
by_share = sorted(reels, key=lambda r: r["shares"],    reverse=True)


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

# ── Section 1: Growth Signals (30d hero cards) ────────────────────────────────
st.markdown('<div class="nh-sec">Growth Signals — Last 30 Days</div>', unsafe_allow_html=True)

h1, h2, h3, h4 = st.columns(4)

with h1:
    st.markdown(f"""
    <div class="hero-card hl">
      <div class="hero-lbl">Views (30d)</div>
      <div class="hero-val bl">{fmt(curr["views"])}</div>
      <div class="hero-delta">{delta_html(curr["views"], prev["views"])}</div>
    </div>
    """, unsafe_allow_html=True)

with h2:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Saves (30d)</div>
      <div class="hero-val gr">{fmt(curr["saves"])}</div>
      <div class="hero-delta">{delta_html(curr["saves"], prev["saves"])}</div>
    </div>
    """, unsafe_allow_html=True)

with h3:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">New Followers (30d)</div>
      <div class="hero-val pu">+{new_followers_30d:,}</div>
      <div class="hero-delta">{delta_html(new_followers_30d, new_followers_prev30)}</div>
    </div>
    """, unsafe_allow_html=True)

with h4:
    st.markdown(f"""
    <div class="hero-card">
      <div class="hero-lbl">Avg Save Rate (30d)</div>
      <div class="hero-val am">{curr["avg_save_rate"]}%</div>
      <div class="hero-delta">{delta_html(curr["avg_save_rate"], prev["avg_save_rate"], " vs prev 30d")}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 2: Account Overview ───────────────────────────────────────────────
st.markdown('<div class="nh-sec">Account Overview</div>', unsafe_allow_html=True)

reels_30d = sum(1 for r in reels if reel_date(r) >= d30_ago)

ao1, ao2, ao3, ao4 = st.columns(4)
account_cards = [
    (ao1, "Followers",       f"{followers:,}",                     "Total audience",          True,  ""),
    (ao2, "Account Reach",   fmt(account_reach_30d) if account_reach_30d else "—", "Last 30 days", False, ""),
    (ao3, "Reels Posted",    str(reels_30d),                       "Last 30 days",            False, ""),
    (ao4, "Total Reels",     str(total_reels),                     "All time",                False, ""),
]
for col, lbl, val, sub, hl, val_cls in account_cards:
    with col:
        klass = "hero-card hl" if hl else "hero-card"
        vcls  = f"hero-val {val_cls}" if val_cls else "hero-val"
        if hl: vcls += " bl"
        st.markdown(f"""
        <div class="{klass}" style="min-height:108px">
          <div class="hero-lbl">{lbl}</div>
          <div class="{vcls}" style="font-size:32px">{val}</div>
          <div class="hero-delta">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 3: Content Performance ────────────────────────────────────────────
st.markdown('<div class="nh-sec">Content Performance</div>', unsafe_allow_html=True)

cp1, cp2, cp3, cp4, cp5 = st.columns(5)
content_cards = [
    (cp1, "Total Views",     fmt(all_["views"]),        "All time",                 ""),
    (cp2, "Avg Views/Reel",  fmt(all_["avg_views"]),    "All reels",                ""),
    (cp3, "Total Saves",     fmt(all_["saves"]),        "All time",                 "gr"),
    (cp4, "Avg Save Rate",   f"{avg_save_r}%",          "All reels",                "am"),
    (cp5, "5K+ Reels",       str(viral_reels),          "Reels that broke through", "pu"),
]
for col, lbl, val, sub, val_cls in content_cards:
    with col:
        vcls = f"hero-val {val_cls}" if val_cls else "hero-val"
        st.markdown(f"""
        <div class="hero-card" style="min-height:108px">
          <div class="hero-lbl">{lbl}</div>
          <div class="{vcls}" style="font-size:32px">{val}</div>
          <div class="hero-delta">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 3: Charts ─────────────────────────────────────────────────────────
cc1, cc2 = st.columns([1.65, 1])

with cc1:
    st.markdown('<div class="nh-sec chart-lbl">Monthly Content Performance</div>', unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trend_labels, y=trend_views, name="Views",
        line=dict(color="#60a5fa", width=2),
        fill="tozeroy", fillcolor="rgba(96,165,250,0.08)",
        mode="lines+markers", marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=trend_labels, y=trend_saves, name="Saves",
        line=dict(color="#4ade80", width=2),
        fill="tozeroy", fillcolor="rgba(74,222,128,0.06)",
        mode="lines+markers", marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=trend_labels, y=trend_shares, name="Shares",
        line=dict(color="#fbbf24", width=2),
        fill="tozeroy", fillcolor="rgba(251,191,36,0.05)",
        mode="lines+markers", marker=dict(size=4),
    ))
    apply_style(fig, height=340)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with cc2:
    st.markdown('<div class="nh-sec chart-lbl">New Followers per Day (60d)</div>', unsafe_allow_html=True)
    fig2 = go.Figure(go.Bar(
        x=fc_dates, y=fc_values,
        marker=dict(color="rgba(74,222,128,0.5)", line=dict(color="#4ade80", width=0)),
        hovertemplate="%{x}: +%{y}<extra></extra>",
    ))
    apply_style(fig2, height=340, show_legend=False)
    fig2.update_layout(xaxis=dict(
        type="category", tickfont=dict(color="#505068", size=9), nticks=10,
    ))
    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 4: Format Analysis + 30d Comparison ──────────────────────────────
fc1, fc2 = st.columns([1.65, 1])

with fc1:
    st.markdown('<div class="nh-sec chart-lbl">Performance by Format — Avg Views per Reel</div>', unsafe_allow_html=True)
    fmt_labels_list = []
    fmt_avg_views   = []
    fmt_avg_saves   = []
    fmt_bar_colors  = []
    for f in FORMAT_ORDER:
        d = fmt_data.get(f)
        if d and d["count"] > 0:
            fmt_labels_list.append(f)
            fmt_avg_views.append(round(d["views"] / d["count"]))
            fmt_avg_saves.append(round(d["saves"] / d["count"]))
            fmt_bar_colors.append(FORMAT_COLORS[f])

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

with fc2:
    def cmp_row_html(label, curr_v, prev_v, color):
        if prev_v == 0:
            delta_str = '<span class="flat">—</span>'
        else:
            pct = (curr_v - prev_v) / prev_v * 100
            sign = "+" if pct >= 0 else ""
            cls  = "up" if pct >= 0 else "dn"
            delta_str = f'<span class="cmp-delta {cls}">{sign}{pct:.0f}%</span>'
        cv = f"{curr_v:,}" if isinstance(curr_v, int) else str(curr_v)
        pv = f"{prev_v:,}" if isinstance(prev_v, int) else str(prev_v)
        return (
            f'<div class="cmp-row">'
            f'<span class="cmp-lbl">{label}</span>'
            f'<span class="cmp-right">'
            f'<span class="cmp-prev">{pv}</span>'
            f'<span class="cmp-arr">→</span>'
            f'<span class="cmp-curr" style="color:{color}">{cv}</span>'
            f'{delta_str}'
            f'</span></div>'
        )

    cmp_html = (
        cmp_row_html("Reel Views",    curr["views"],   prev["views"],   "#60a5fa") +
        cmp_row_html("Saves",         curr["saves"],   prev["saves"],   "#4ade80") +
        cmp_row_html("Shares",        curr["shares"],  prev["shares"],  "#fbbf24") +
        cmp_row_html("New Followers", new_followers_30d, new_followers_prev30, "#a78bfa") +
        cmp_row_html("Reels Posted",  curr["count"],   prev["count"],   "#d8d8e6")
    )
    st.markdown(f"""
    <div class="chart-card">
      <div class="nh-sec">Last 30 Days vs Previous 30</div>
      <div class="cmp-wrap">{cmp_html}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 5: Goals + Content Mix ───────────────────────────────────────────
gc1, gc2 = st.columns([1.3, 1])

with gc1:
    def goal_bar_html(label, curr_val, goal_val, curr_str, goal_str):
        p = min(round((curr_val / goal_val) * 100), 100) if goal_val else 0
        if p >= 100:   color = "#4ade80"; icon = "✓"
        elif p >= 65:  color = "#fbbf24"; icon = "△"
        else:          color = "#f87171"; icon = "○"
        return (
            f'<div class="goal-row">'
            f'<div class="goal-top">'
            f'<span class="goal-lbl">{icon} {label}</span>'
            f'<span class="goal-vv" style="color:{color}">{curr_str}'
            f' <span class="goal-tgt">/ {goal_str}</span></span>'
            f'</div>'
            f'<div class="goal-bg"><div class="goal-fill" '
            f'style="width:{p}%;background:{color}"></div></div>'
            f'</div>'
        )

    goals_html = (
        goal_bar_html("New Followers (30d)", new_followers_30d,
                      goal_monthly_followers,
                      str(new_followers_30d), str(goal_monthly_followers)) +
        goal_bar_html("Monthly Views", curr["views"],
                      goal_monthly_views,
                      fmt(curr["views"]), fmt(goal_monthly_views)) +
        goal_bar_html("Avg Save Rate", curr["avg_save_rate"],
                      goal_avg_save_rate,
                      f"{curr['avg_save_rate']}%", f"{goal_avg_save_rate}%") +
        goal_bar_html("5K+ Reels (total)", viral_reels,
                      goal_5k_reels,
                      str(viral_reels), str(goal_5k_reels))
    )
    st.markdown(f"""
    <div class="chart-card">
      <div class="nh-sec">Goals — Trajectory-Based Targets</div>
      {goals_html}
    </div>
    """, unsafe_allow_html=True)

with gc2:
    st.markdown('<div class="nh-sec chart-lbl">Content Mix</div>', unsafe_allow_html=True)
    mix_labels = []
    mix_counts = []
    mix_colors = []
    for f in FORMAT_ORDER:
        d = fmt_data.get(f)
        if d and d["count"] > 0:
            mix_labels.append(f"{f} ({d['count']})")
            mix_counts.append(d["count"])
            mix_colors.append(FORMAT_COLORS[f])
    fig4 = go.Figure(go.Pie(
        labels=mix_labels, values=mix_counts,
        marker=dict(colors=mix_colors, line=dict(width=0)),
        hole=0.68, hovertemplate="%{label}: %{value} reels<extra></extra>",
        textinfo="none",
    ))
    apply_style(fig4, height=280, show_legend=True, legend_right=True)
    fig4.update_layout(margin=dict(l=8, r=140, t=12, b=12))
    st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 6: Best Performers ────────────────────────────────────────────────
st.markdown('<div class="nh-sec">Best Performers</div>', unsafe_allow_html=True)
bp1, bp2, bp3 = st.columns(3)

def perf_card_html(label, color, reel):
    if not reel:
        return ""
    cap      = trunc(reel.get("caption", ""), 62).replace('"', "'")
    fmt_name = reel.get("format", "Other")
    fc       = FORMAT_COLORS.get(fmt_name, "#9ca3af")
    thumb    = reel.get("thumbnail", "")
    thumb_html = (
        f'<img src="{thumb}" class="perf-thumb" onerror="this.style.display=\'none\'">'
        if thumb else ""
    )
    link = reel.get("permalink", "#")
    return f"""
    <div class="perf-card">
      {thumb_html}
      <div class="perf-lbl" style="color:{color}">{label}</div>
      <div class="perf-cap">{cap or reel.get("shortcode", "")}</div>
      <div class="perf-tag">
        <span class="tag" style="background:{fc}22;color:{fc};border:1px solid {fc}44">{fmt_name}</span>
      </div>
      <div class="perf-stats">
        <div class="perf-m"><span style="color:#60a5fa">{reel.get("views",0):,}</span>Views</div>
        <div class="perf-m"><span style="color:#4ade80">{reel.get("saves",0)}</span>Saves</div>
        <div class="perf-m"><span style="color:#fbbf24">{reel.get("shares",0)}</span>Shares</div>
        <div class="perf-m"><span style="color:#a78bfa">{reel.get("save_rate",0)}%</span>Save rate</div>
      </div>
    </div>"""

with bp1:
    st.markdown(perf_card_html("Most Viewed",   "#60a5fa", by_views[0] if by_views else None), unsafe_allow_html=True)
with bp2:
    st.markdown(perf_card_html("Top Save Rate", "#4ade80", by_saver[0] if by_saver else None), unsafe_allow_html=True)
with bp3:
    st.markdown(perf_card_html("Most Shared",   "#fbbf24", by_share[0] if by_share else None), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Section 7: All Reels Table ────────────────────────────────────────────────
st.markdown('<div class="nh-sec">All Reels</div>', unsafe_allow_html=True)

def reel_row_html(r):
    cap   = trunc(r.get("caption", "") or r.get("shortcode", ""), 75).replace("<", "&lt;")
    fname = r.get("format", "Other")
    fc    = FORMAT_COLORS.get(fname, "#9ca3af")
    link  = r.get("permalink", "")
    link_html = f'<a href="{link}" target="_blank">Open ↗</a>' if link else ""
    return (
        f"<tr>"
        f'<td class="dt">{r["date"]}</td>'
        f'<td class="cap">{cap}</td>'
        f'<td><span class="tag-sm" style="background:{fc}22;color:{fc};border:1px solid {fc}44">{fname}</span></td>'
        f'<td class="num">{r["views"]:,}</td>'
        f'<td class="num">{r["likes"]:,}</td>'
        f'<td class="num">{r["saves"]:,}</td>'
        f'<td class="num">{r["shares"]:,}</td>'
        f'<td class="num">{r["save_rate"]:.2f}%</td>'
        f'<td>{link_html}</td>'
        f"</tr>"
    )

table_html = (
    '<div class="nh-tbl-wrap"><table class="nh-tbl">'
    '<thead><tr>'
    '<th>Date</th><th>Caption</th><th>Format</th>'
    '<th style="text-align:right">Views</th>'
    '<th style="text-align:right">Likes</th>'
    '<th style="text-align:right">Saves</th>'
    '<th style="text-align:right">Shares</th>'
    '<th style="text-align:right">Save %</th>'
    '<th>Link</th>'
    '</tr></thead><tbody>'
    + "".join(reel_row_html(r) for r in by_views)
    + '</tbody></table></div>'
)
st.markdown(table_html, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#2a2a3a;font-size:11px;padding-top:18px;font-weight:500">
  {total_reels} reels &middot; @noah.haupt &middot; synced {synced}
</div>
""", unsafe_allow_html=True)
