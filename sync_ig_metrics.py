#!/usr/bin/env python3
"""
Instagram full sync: account stats + all reels -> metrics.json
Runs automatically on double-click via Run Dashboard.bat

SETUP (one-time):
  Set META_ACCESS_TOKEN and META_IG_USER_ID as User environment variables.

DAILY USE:
  Double-click Run Dashboard.bat  (syncs then opens dashboard)
  Or double-click Run Sync IG Metrics.bat  (sync only)
"""

import os, sys, subprocess, time, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Fix Windows cp1252 encoding — captions can contain emoji/Unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_IG_USER_ID   = os.environ.get("META_IG_USER_ID", "")
SCRIPT_DIR        = Path(__file__).parent
METRICS_FILE      = SCRIPT_DIR / "metrics.json"
GRAPH_BASE        = "https://graph.instagram.com/v21.0"

# ── Format detection (kept in sync so it's stored in metrics.json) ────────────
# generate_dashboard.py reads the stored value — no re-detection on dashboard load.
# To override a format: edit the "format" field directly in metrics.json.

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

def ensure_deps():
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])

ensure_deps()
import requests

def validate():
    if not META_ACCESS_TOKEN:
        print("META_ACCESS_TOKEN not set.")
        if sys.stdin.isatty(): input("\nPress Enter to close...")
        sys.exit(1)

# ── Account-level data ────────────────────────────────────────────────────────

def fetch_account_profile() -> dict:
    """Fetches basic profile: followers, following, bio, website."""
    r = requests.get(f"{GRAPH_BASE}/me", params={
        "fields": "id,username,followers_count,follows_count,biography,website",
        "access_token": META_ACCESS_TOKEN
    })
    data = r.json()
    if "error" in data:
        print(f"   Profile error: {data['error'].get('message','')[:80]}")
        return {}
    return {
        "username":  data.get("username", ""),
        "followers": data.get("followers_count", 0),
        "following": data.get("follows_count", 0),
        "biography": data.get("biography", ""),
        "website":   data.get("website", ""),
    }

def fetch_account_insight(metric: str, days: int = 90) -> dict | None:
    """Fetches a single daily account insight for the last N days."""
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    until = int(datetime.now(timezone.utc).timestamp())
    r = requests.get(f"{GRAPH_BASE}/me/insights", params={
        "metric": metric, "period": "day",
        "since": since, "until": until,
        "access_token": META_ACCESS_TOKEN
    })
    data = r.json()
    if "error" in data:
        return None
    for item in data.get("data", []):
        vals = item.get("values", [])
        if not vals:
            return None
        return {
            "total":   sum(v.get("value", 0) for v in vals),
            "history": [{"date": v["end_time"][:10], "value": v.get("value", 0)} for v in vals]
        }
    return None

def fetch_account_stats() -> dict:
    """Fetches all available account-level stats. Gracefully skips unavailable metrics."""
    print("\n   Fetching account stats...")

    profile = fetch_account_profile()
    if profile:
        print(f"   @{profile['username']} — {profile['followers']:,} followers")
    else:
        print("   Could not fetch profile")

    insights = {}
    metrics_to_try = [
        ("follower_count",    "New followers"),
        ("reach",             "Account reach"),
        ("profile_views",     "Profile views"),
        ("website_clicks",    "Website clicks"),
        ("total_interactions","Interactions"),
        ("accounts_engaged",  "Engaged accounts"),
    ]

    for metric, label in metrics_to_try:
        result = fetch_account_insight(metric, days=90)
        if result:
            insights[metric] = result
            print(f"   {label}: {result['total']:,} (90d)")
        else:
            print(f"   {label}: not available with current token")

    return {"account_profile": profile, "account_insights": insights}

# ── Reel-level data ───────────────────────────────────────────────────────────

def fetch_all_reels() -> list[dict]:
    """Fetches every reel from the account via Graph API."""
    print("\n   Fetching all reels...")
    reels = []
    url = f"{GRAPH_BASE}/me/media"
    params = {
        "fields": "id,shortcode,timestamp,media_type,media_product_type,permalink,caption,thumbnail_url,comments_count",
        "access_token": META_ACCESS_TOKEN,
        "limit": 100
    }
    while url:
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            print(f"   Error fetching media: {data['error'].get('message')}")
            return []
        for item in data.get("data", []):
            if item.get("media_product_type") == "REELS":
                reels.append(item)
        url = data.get("paging", {}).get("next")
        params = {}
    print(f"   Found {len(reels)} reels")
    return reels

def fetch_insights(media_id: str, media_type: str = "VIDEO") -> dict:
    """Fetches insights for one reel. Uses the set of metrics the IG Graph API
    currently supports for Reels (as of April 2026). Falls back gracefully for
    non-reel media or permission-gated metrics."""
    is_video = media_type in ("VIDEO", "REEL")
    # plays/follows/profile_visits are deprecated for REELS — do not request.
    if is_video:
        metrics = "reach,saved,shares,likes,total_interactions,ig_reels_avg_watch_time,ig_reels_video_view_total_time"
    else:
        metrics = "reach,saved,shares,likes"

    r = requests.get(
        f"{GRAPH_BASE}/{media_id}/insights",
        params={"metric": metrics, "access_token": META_ACCESS_TOKEN}
    )
    data = r.json()
    if "error" in data:
        # Fallback: minimal metric set
        r2 = requests.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={"metric": "reach,saved,shares,likes", "access_token": META_ACCESS_TOKEN}
        )
        data = r2.json()
        if "error" in data:
            return {}
    result = {}
    for item in data.get("data", []):
        values = item.get("values", [])
        result[item["name"]] = values[0]["value"] if values else item.get("value", 0)
    return result

def load_existing() -> dict:
    """Loads existing metrics.json, preserving account stats. Returns reel map keyed by shortcode."""
    if METRICS_FILE.exists():
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "reels_map": {r["shortcode"]: r for r in data.get("reels", [])},
            "account_profile":  data.get("account_profile", {}),
            "account_insights": data.get("account_insights", {}),
        }
    return {"reels_map": {}, "account_profile": {}, "account_insights": {}}

# ── GitHub push (Streamlit Cloud deployment) ──────────────────────────────────

def push_to_github(metrics_file: Path):
    """
    Push metrics.json to a GitHub repo so Streamlit Cloud can read it.
    Only runs when METRICS_GITHUB_TOKEN and METRICS_GITHUB_REPO are set.

    One-time setup:
      1. Create a private GitHub repo (e.g. your-user/noah-ig-dashboard)
      2. Generate a GitHub Personal Access Token with 'repo' scope
      3. setx METRICS_GITHUB_TOKEN "ghp_your-token"
      4. setx METRICS_GITHUB_REPO  "your-user/noah-ig-dashboard"
    """
    import base64 as _b64

    token = os.environ.get("METRICS_GITHUB_TOKEN", "")
    repo  = os.environ.get("METRICS_GITHUB_REPO",  "")
    path  = os.environ.get("METRICS_GITHUB_PATH",  "metrics.json")

    if not (token and repo):
        return  # silently skip — GitHub push is optional

    print("\n   Pushing metrics.json to GitHub...")
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }

    # Get current file SHA (required for updates; None for first push)
    r_get = requests.get(api_url, headers=headers)
    sha   = r_get.json().get("sha", "") if r_get.status_code == 200 else ""

    content = _b64.b64encode(metrics_file.read_bytes()).decode()
    body    = {
        "message": f"metrics: sync {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        "content": content,
    }
    if sha:
        body["sha"] = sha

    r_put = requests.put(api_url, headers=headers, json=body)
    if r_put.status_code in (200, 201):
        print("   Pushed to GitHub — Streamlit dashboard will update shortly")
    else:
        print(f"   GitHub push failed ({r_put.status_code}) — dashboard not updated")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("   Instagram Full Sync")
    print("=" * 52)

    validate()

    # ── Step 1: Account stats ─────────────────────────────────────────────────
    account_data = fetch_account_stats()

    # ── Step 2: Reels ─────────────────────────────────────────────────────────
    reels = fetch_all_reels()
    if not reels:
        print("No reels found.")
        if sys.stdin.isatty(): input("\nPress Enter to close...")
        return

    existing = load_existing()
    existing_reels = existing["reels_map"]
    results = []
    synced = new_count = failed = skipped = 0

    # Only fetch fresh API data for reels posted in the last 30 days.
    # Older reels carry over their last-known metrics — numbers don't move after 30 days.
    # To force a full refresh: python sync_ig_metrics.py --full
    full_sync = "--full" in sys.argv
    today_date = datetime.now(timezone.utc).date()
    cutoff     = str(today_date - timedelta(days=30))

    active = sum(1 for r in reels if r.get("timestamp", "")[:10] >= cutoff)
    if full_sync:
        print(f"\n   Full sync — all {len(reels)} reels...\n")
    else:
        print(f"\n   Syncing {active} recent reels (last 30d), carrying over {len(reels)-active} older...\n")

    for i, reel in enumerate(reels, 1):
        sc        = reel.get("shortcode", "").lower()
        caption   = reel.get("caption", "") or ""
        title     = caption[:60].replace("\n", " ") if caption else sc
        reel_date = reel.get("timestamp", "")[:10]
        print(f"[{i}/{len(reels)}] {title[:50]}")

        # Carry over existing data for reels older than 30 days
        if not full_sync and reel_date < cutoff and sc in existing_reels:
            results.append(existing_reels[sc])
            skipped += 1
            print(f"   Carried over (posted {reel_date})")
            continue

        insights = fetch_insights(reel["id"], reel.get("media_type", "VIDEO"))

        if not insights:
            print("   Failed to get insights")
            failed += 1
            if sc in existing_reels:
                results.append(existing_reels[sc])
            continue

        reach          = insights.get("reach", 0)
        avg_watch_ms   = insights.get("ig_reels_avg_watch_time", 0) or 0
        total_watch_ms = insights.get("ig_reels_video_view_total_time", 0) or 0
        # True plays = total_watch_time / avg_watch_time. Falls back to reach.
        derived_plays  = round(total_watch_ms / avg_watch_ms) if avg_watch_ms else 0
        views          = derived_plays if derived_plays else reach

        # Preserve stored format (lets manual edits survive re-syncs).
        # To override: edit "format" directly in metrics.json.
        stored_format = existing_reels.get(sc, {}).get("format")
        fmt_tag = stored_format if stored_format else detect_format(caption)

        # Preserve duration if transcribe step has already written it
        stored_duration = existing_reels.get(sc, {}).get("duration_sec")

        # Rates: use views (derived plays) as denominator. Better than reach —
        # reach counts unique accounts; views/plays counts actual engagements.
        denom = views or reach or 0

        entry = {
            "id":              reel["id"],
            "shortcode":       sc,
            "permalink":       reel.get("permalink", f"https://www.instagram.com/reel/{sc}/"),
            "date":            reel.get("timestamp", "")[:10],
            "caption":         caption[:200],
            "thumbnail":       reel.get("thumbnail_url", ""),
            "format":          fmt_tag,
            "views":           views,
            "reach":           reach,
            "likes":           insights.get("likes", 0),
            "saves":           insights.get("saved", 0),
            "shares":          insights.get("shares", 0),
            "comments":        reel.get("comments_count", 0),
            "total_interactions": insights.get("total_interactions", 0),
            "avg_watch_ms":    avg_watch_ms,
            "total_watch_ms":  total_watch_ms,
            "duration_sec":    stored_duration,   # filled by transcribe_posted_reels.py
            "save_rate":       round(insights.get("saved", 0) / denom * 100, 2) if denom else 0,
            "share_rate":      round(insights.get("shares", 0) / denom * 100, 2) if denom else 0,
            "completion_rate": round((avg_watch_ms / 1000) / stored_duration * 100, 2) if (avg_watch_ms and stored_duration) else None,
            "synced_at":       datetime.now(timezone.utc).isoformat()
        }

        if sc not in existing_reels:
            new_count += 1
            print(f"   NEW | views={views}, saves={entry['saves']}, shares={entry['shares']}, likes={entry['likes']}")
        else:
            synced += 1
            print(f"   views={views}, saves={entry['saves']}, shares={entry['shares']}, likes={entry['likes']}")

        results.append(entry)
        time.sleep(1)

    # ── Step 3: Write metrics.json ────────────────────────────────────────────
    output = {
        "account":          "noah.haupt",
        "ig_user_id":       META_IG_USER_ID,
        "last_sync":        datetime.now(timezone.utc).isoformat(),
        "total_reels":      len(results),
        "account_profile":  account_data.get("account_profile", {}),
        "account_insights": account_data.get("account_insights", {}),
        "reels":            results
    }
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    followers = account_data.get("account_profile", {}).get("followers", 0)
    print(f"\n{'='*52}")
    print(f"   Done: {synced} updated, {new_count} new, {skipped} carried over, {failed} failed")
    print(f"   Followers: {followers:,}")
    print(f"   Saved to: metrics.json")
    print(f"{'='*52}")

    # Publishing to GitHub is handled by auto_sync_dashboard.bat after the full
    # chain runs (IG sync -> push_to_notion -> transcribe -> pillar sync -> git push).
    # Pushing here would publish a pillar-less metrics.json, wiping the dashboard's
    # Format column until the next full chain completes. So we don't push here.

    if sys.stdin.isatty(): input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
