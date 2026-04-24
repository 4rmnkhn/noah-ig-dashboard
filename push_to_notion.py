#!/usr/bin/env python3
"""
Push IG reel metrics from metrics.json → Notion IG Reels Tracker.

Safe by design:
  - NEVER deletes any Notion page
  - Only touches pages it can match by Post Link (permalink)
  - Planning/script rows (no Post Link match) are untouched
  - Upserts: updates existing, creates new — nothing else

Run after sync_ig_metrics.py, or double-click Run Push to Notion.bat.

SETUP (one-time):
  setx NOTION_API_KEY "ntn_your-notion-token"
"""

import os, sys, json, time, subprocess
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
DATABASE_ID    = "33c16ed009eb811a9296c64de64e87f4"   # IG Reels Tracker
SCRIPT_DIR     = Path(__file__).parent
METRICS_FILE   = SCRIPT_DIR / "metrics.json"

def ensure_deps():
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])

ensure_deps()
import requests

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ── Validate ──────────────────────────────────────────────────────────────────

def validate():
    if not NOTION_API_KEY:
        print("NOTION_API_KEY not set.")
        print("Run: setx NOTION_API_KEY \"ntn_your-token\"")
        if sys.stdin.isatty(): input("\nPress Enter to close...")
        sys.exit(1)
    if not METRICS_FILE.exists():
        print("metrics.json not found. Run sync_ig_metrics.py first.")
        if sys.stdin.isatty(): input("\nPress Enter to close...")
        sys.exit(1)

# ── Load existing Notion pages (build permalink → page_id map) ────────────────

def load_existing_pages() -> dict:
    """
    Returns {permalink: page_id} for every Notion page that has Post Link set.
    Pages without Post Link (planning/script rows) are never included — and
    therefore never touched.
    """
    print("   Loading existing Notion pages...")
    pages = {}
    cursor = None

    while True:
        body = {
            "filter": {"property": "Post Link", "url": {"is_not_empty": True}},
            "page_size": 100
        }
        if cursor:
            body["start_cursor"] = cursor

        resp = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=HEADERS,
            json=body
        )
        data = resp.json()

        if "error" in data:
            print(f"   Notion error: {data.get('message','')[:100]}")
            return {}

        for page in data.get("results", []):
            pl = page["properties"].get("Post Link", {}).get("url", "")
            if pl:
                pages[pl.rstrip("/")] = page["id"]

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    print(f"   Found {len(pages)} existing reel pages in Notion")
    return pages

# ── Upsert operations ─────────────────────────────────────────────────────────

def _metrics_props(entry: dict) -> dict:
    """Builds the metrics-only properties dict (safe to PATCH on any existing page)."""
    props = {
        "Views":      {"number": entry.get("views",   0)},
        "Likes":      {"number": entry.get("likes",   0)},
        "Saves":      {"number": entry.get("saves",   0)},
        "Shares":     {"number": entry.get("shares",  0)},
        "New Follows":{"number": entry.get("follows", 0)},
    }
    fmt = entry.get("format")
    if fmt:
        props["Format"] = {"select": {"name": fmt}}
    return props


def update_page(page_id: str, entry: dict) -> bool:
    """Updates only metric fields on an existing page. User-managed fields untouched."""
    resp = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": _metrics_props(entry)}
    )
    return resp.status_code in (200, 201)


def create_page(entry: dict) -> bool:
    """
    Creates a new Notion page for a reel not yet tracked.
    transcribe_posted_reels.py reads Post Link directly — no Reference Link needed.
    """
    caption  = (entry.get("caption", "") or "").replace("\n", " ").strip()
    title    = caption[:100] or entry.get("shortcode", "")
    permalink = entry.get("permalink", "")

    props = {
        "Name":       {"title": [{"text": {"content": title}}]},
        "Post Link":  {"url": permalink},
        "Status":     {"status": {"name": "Posted"}},
        **_metrics_props(entry)
    }

    date_str = entry.get("date", "")
    if date_str:
        props["Post Date"] = {"date": {"start": date_str}}

    body = {
        "parent": {"database_id": DATABASE_ID},
        "properties": props,
        # No body content — transcribe_posted_reels.py adds the transcript separately
    }

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json=body
    )
    return resp.status_code in (200, 201)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("   Notion Push — IG Reels Tracker")
    print("=" * 52)

    validate()

    with open(METRICS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    reels = data.get("reels", [])
    if not reels:
        print("No reels in metrics.json.")
        if sys.stdin.isatty(): input("\nPress Enter to close...")
        return

    existing = load_existing_pages()

    updated = created = failed = skipped = 0
    print(f"\n   Pushing {len(reels)} reels to Notion...\n")

    for i, reel in enumerate(reels, 1):
        permalink = reel.get("permalink", "").rstrip("/")
        caption   = (reel.get("caption", "") or "")[:50].replace("\n", " ")
        label     = caption or reel.get("shortcode", "")

        print(f"[{i}/{len(reels)}] {label[:48]}")

        if not permalink:
            print("   No permalink — skipped")
            skipped += 1
            continue

        if permalink in existing:
            ok = update_page(existing[permalink], reel)
            if ok:
                updated += 1
                print(f"   Updated")
            else:
                failed += 1
                print(f"   Update failed")
        else:
            ok = create_page(reel)
            if ok:
                created += 1
                print(f"   NEW — created in Notion")
            else:
                failed += 1
                print(f"   Create failed")

        # Notion rate limit: ~3 req/sec, stay safe
        time.sleep(0.4)

    print(f"\n{'='*52}")
    print(f"   Done: {updated} updated, {created} new, {failed} failed, {skipped} skipped")
    print(f"   Notion DB: notion.so/{DATABASE_ID}")
    print(f"{'='*52}")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
