#!/usr/bin/env python3
"""
One-off: archive Notion IG Reels Tracker pages with Post Date before 2026-04-03.
Keeps Apr 3 onwards (first Arman-Noah collab reel "3 tips to close").

Usage:
    python archive_pre_collab.py            # dry-run (lists what would be archived)
    python archive_pre_collab.py --apply    # actually archive
"""

import os, sys, time
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
DATABASE_ID    = "33c16ed009eb811a9296c64de64e87f4"
CUTOFF_DATE    = "2026-04-03"  # archive strictly before this

if not NOTION_API_KEY:
    print("NOTION_API_KEY not set"); sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

APPLY = "--apply" in sys.argv

def query_pages():
    pages = []
    cursor = None
    while True:
        body = {
            "page_size": 100,
            "filter": {
                "and": [
                    {"property": "Status", "status": {"equals": "Posted"}},
                    {"property": "Post Date", "date": {"before": CUTOFF_DATE}},
                ]
            },
        }
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=HEADERS, json=body, timeout=30,
        )
        d = r.json()
        if d.get("object") == "error":
            print("Notion error:", d.get("message", "")[:300])
            sys.exit(1)
        pages.extend(d.get("results", []))
        if d.get("has_more"):
            cursor = d.get("next_cursor")
        else:
            break
    return pages

def title_of(page):
    props = page.get("properties", {})
    for k, v in props.items():
        if v.get("type") == "title":
            t = v.get("title", [])
            return "".join(x.get("plain_text", "") for x in t) or "(untitled)"
    return "(untitled)"

def post_date_of(page):
    d = (page.get("properties", {}).get("Post Date", {}) or {}).get("date") or {}
    return d.get("start", "")

def archive(page_id):
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS, json={"archived": True}, timeout=30,
    )
    return r.status_code == 200, r.text[:200]

def main():
    pages = query_pages()
    print(f"Found {len(pages)} pages with Status=Posted AND Post Date before {CUTOFF_DATE}")
    print()
    for p in pages[:10]:
        print(f"  {post_date_of(p)}  {title_of(p)[:80]}")
    if len(pages) > 10:
        print(f"  ... and {len(pages) - 10} more")
    print()
    if not APPLY:
        print("DRY RUN — re-run with --apply to archive.")
        return
    print("Archiving...")
    ok = 0
    fail = 0
    for i, p in enumerate(pages, 1):
        success, msg = archive(p["id"])
        if success:
            ok += 1
        else:
            fail += 1
            print(f"   FAIL [{i}]: {msg}")
        if i % 10 == 0:
            print(f"   {i}/{len(pages)}...")
        time.sleep(0.34)  # ~3 req/s, Notion rate-limit safe
    print(f"Done. Archived {ok}, failed {fail}.")

if __name__ == "__main__":
    main()
