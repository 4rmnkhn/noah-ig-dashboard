#!/usr/bin/env python3
"""
Push IG reel metrics from metrics.json → Notion IG Reels Tracker.

Update-or-orphan logic:
  1. Match by Post Link → update metrics on existing page (fast path)
  2. Else match by caption-from-body against planning rows
     (Status ∈ Ready to film / Edited / Filmed). On hit: write Post Link +
     Post Date + metrics + Status=Posted to that planning row. No new row.
  3. Else create orphan row with Source="Noah Solo", Status=Posted.

Never deletes anything.

Run after sync_ig_metrics.py, or double-click Run Push to Notion.bat.

SETUP (one-time):
  setx NOTION_API_KEY "ntn_your-notion-token"
"""

import os, sys, json, time, subprocess, re
from pathlib import Path
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
DATABASE_ID    = "33c16ed009eb811a9296c64de64e87f4"   # IG Reels Tracker
SCRIPT_DIR     = Path(__file__).parent
METRICS_FILE   = SCRIPT_DIR / "metrics.json"

PLANNING_STATUSES = ["Ready to film", "Edited", "Filmed", "Draft"]
CUTOFF_DATE = date(2026, 4, 3)  # delivery start — older reels skipped

SHORTCODE_RE = re.compile(r"/(?:p|reel|reels)/([^/?]+)")

def shortcode(url: str) -> str:
    """Extract IG shortcode from any /p/, /reel/, or /reels/ URL form. Robust to
    /p/X vs /reel/X mismatch (same reel, different wrapper)."""
    if not url:
        return ""
    m = SHORTCODE_RE.search(url)
    return m.group(1) if m else ""

def ensure_deps():
    try:
        import requests  # noqa
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])

ensure_deps()
import requests
from notion_matcher import fetch_blocks, extract_caption, captions_match

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

# ── Load existing pages by Post Link ──────────────────────────────────────────

def load_existing_pages() -> dict:
    """{shortcode: page_id} for every page with Post Link set. Shortcode-keyed
    so /p/X and /reel/X collapse to one entry."""
    print("   Loading existing reel pages (by Post Link shortcode)...")
    pages = {}
    cursor = None
    while True:
        body = {
            "filter": {"property": "Post Link", "url": {"is_not_empty": True}},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=HEADERS, json=body, timeout=30,
        )
        data = resp.json()
        if "error" in data:
            print(f"   Notion error: {data.get('message','')[:100]}")
            return {}
        for page in data.get("results", []):
            pl = page["properties"].get("Post Link", {}).get("url", "")
            sc = shortcode(pl)
            if sc:
                pages[sc] = page["id"]
        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break
    print(f"   Found {len(pages)} unique reels with Post Link")
    return pages

# ── Load match candidates (planning rows w/ caption in body) ──────────────────

def load_match_candidates() -> list:
    """Returns [{id, title, caption}] for rows in PLANNING_STATUSES that have a
    caption block in their body. Used as the second-pass matcher when a reel
    misses the Post Link map."""
    print("   Loading planning-row candidates (Status: Ready to film / Edited / Filmed / Draft)...")
    rows = []
    cursor = None
    status_filters = [{"property": "Status", "status": {"equals": s}} for s in PLANNING_STATUSES]
    while True:
        body = {
            "filter": {"or": status_filters},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=HEADERS, json=body, timeout=30,
        )
        data = resp.json()
        if "error" in data:
            print(f"   Notion error loading candidates: {data.get('message','')[:100]}")
            return []
        rows.extend(data.get("results", []))
        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    candidates = []
    for p in rows:
        blocks = fetch_blocks(p["id"])
        cap = extract_caption(blocks)
        if cap:
            title_prop = next((v for v in p.get("properties", {}).values() if v.get("type") == "title"), {})
            title = "".join(t.get("plain_text", "") for t in title_prop.get("title", []))
            candidates.append({"id": p["id"], "title": title, "caption": cap})
        time.sleep(0.05)
    print(f"   {len(candidates)} planning rows with captions in body")
    return candidates

# ── Properties helpers ────────────────────────────────────────────────────────

def _metrics_props(entry: dict) -> dict:
    """Metric-only props (safe to PATCH on any page)."""
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


def _post_props(entry: dict) -> dict:
    """Full post payload: Post Link + Post Date + metrics + Status=Posted.
    Used when promoting a planning row to Posted via caption match."""
    props = {
        "Post Link": {"url": entry.get("permalink", "")},
        "Status":    {"status": {"name": "Posted"}},
        **_metrics_props(entry),
    }
    date_str = entry.get("date", "")
    if date_str:
        props["Post Date"] = {"date": {"start": date_str}}
    return props

# ── Mutations ─────────────────────────────────────────────────────────────────

def update_metrics(page_id: str, entry: dict) -> bool:
    """Metrics-only PATCH on existing posted page."""
    resp = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS, json={"properties": _metrics_props(entry)}, timeout=30,
    )
    return resp.status_code in (200, 201)


def promote_planning_row(page_id: str, entry: dict) -> bool:
    """Caption-matched a planning row: write Post Link + Post Date + metrics + Status=Posted."""
    resp = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS, json={"properties": _post_props(entry)}, timeout=30,
    )
    return resp.status_code in (200, 201)


def create_orphan(entry: dict) -> bool:
    """No planning row matched. Create a fresh page tagged Source=Noah Solo."""
    caption  = (entry.get("caption", "") or "").replace("\n", " ").strip()
    title    = caption[:100] or entry.get("shortcode", "")
    permalink = entry.get("permalink", "")

    props = {
        "Name":       {"title": [{"text": {"content": title}}]},
        "Post Link":  {"url": permalink},
        "Status":     {"status": {"name": "Posted"}},
        "Source":     {"select": {"name": "Noah Solo"}},
        "Pillar":     {"select": {"name": "Talking-Head"}},
        **_metrics_props(entry),
    }
    date_str = entry.get("date", "")
    if date_str:
        props["Post Date"] = {"date": {"start": date_str}}

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json={"parent": {"database_id": DATABASE_ID}, "properties": props},
        timeout=30,
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
    candidates = load_match_candidates()
    matched_candidate_ids = set()

    updated = promoted = created = failed = skipped = pre_cutoff = 0
    print(f"\n   Pushing {len(reels)} reels to Notion (cutoff: {CUTOFF_DATE.isoformat()})...\n")

    for i, reel in enumerate(reels, 1):
        permalink = reel.get("permalink", "")
        sc = shortcode(permalink)
        caption_preview = (reel.get("caption", "") or "")[:50].replace("\n", " ")
        label = caption_preview or reel.get("shortcode", "")

        if not permalink:
            skipped += 1
            continue

        # Date filter: skip pre-collab reels silently (counted only)
        date_str = reel.get("date", "")
        if date_str:
            try:
                d = date.fromisoformat(date_str[:10])
                if d < CUTOFF_DATE:
                    pre_cutoff += 1
                    continue
            except ValueError:
                pass

        print(f"[{i}/{len(reels)}] {label[:48]}")

        # Path 1: shortcode match → metrics-only update
        if sc and sc in existing:
            if update_metrics(existing[sc], reel):
                updated += 1
                print(f"   Updated metrics")
            else:
                failed += 1
                print(f"   Update failed")
            time.sleep(0.4)
            continue

        # Path 2: caption match against planning rows → promote
        ig_caption = reel.get("caption", "") or ""
        match = None
        for c in candidates:
            if c["id"] in matched_candidate_ids:
                continue
            if captions_match(ig_caption, c["caption"]):
                match = c
                break

        if match:
            if promote_planning_row(match["id"], reel):
                promoted += 1
                matched_candidate_ids.add(match["id"])
                print(f"   PROMOTED planning row → Posted: {match['title'][:50]}")
            else:
                failed += 1
                print(f"   Promote failed")
            time.sleep(0.4)
            continue

        # Path 3: orphan
        if create_orphan(reel):
            created += 1
            print(f"   ORPHAN — created (Source=Noah Solo)")
        else:
            failed += 1
            print(f"   Create failed")
        time.sleep(0.4)

    print(f"\n{'='*52}")
    print(f"   Done: {updated} metric-updated, {promoted} promoted, {created} orphans, {failed} failed, {skipped} no-permalink, {pre_cutoff} pre-cutoff")
    print(f"   Notion DB: notion.so/{DATABASE_ID}")
    print(f"{'='*52}")
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
