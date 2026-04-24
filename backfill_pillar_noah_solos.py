#!/usr/bin/env python3
"""
One-time backfill: any IG Reels Tracker page with blank Pillar that contains
only a "Reel Transcript" heading (no manual script body) is a Noah solo upload.
Set its Pillar to "Talking-Head".

Pages with blank Pillar but a real script body are Arman's scripted reels he
hasn't tagged yet — left alone for manual tagging.
"""
import os, sys, json
import requests
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
DATABASE_ID    = "33c16ed009eb811a9296c64de64e87f4"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Headings that indicate auto-generated content (not a manual script).
AUTO_HEADINGS = {"reel transcript", "reference transcript"}

def fetch_blank_pillar_pages():
    """Returns [(page_id, title)] for pages with Post Link set + Pillar empty."""
    out, cursor = [], None
    while True:
        body = {
            "filter": {
                "and": [
                    {"property": "Post Link", "url": {"is_not_empty": True}},
                    {"property": "Pillar",   "select": {"is_empty": True}},
                ]
            },
            "page_size": 100,
        }
        if cursor: body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
                          headers=HEADERS, json=body, timeout=30)
        d = r.json()
        for p in d.get("results", []):
            t = p["properties"].get("Name", {}).get("title", [])
            title = t[0]["plain_text"] if t else "(untitled)"
            out.append((p["id"], title[:60]))
        if d.get("has_more"): cursor = d.get("next_cursor")
        else: break
    return out

def page_is_noah_solo(page_id: str) -> bool:
    """A page is a Noah solo if its body has no headings other than the
    auto-generated transcript headings (Reel Transcript / Reference Transcript)."""
    r = requests.get(f"https://api.notion.com/v1/blocks/{page_id}/children",
                     headers=HEADERS, timeout=30)
    blocks = r.json().get("results", [])
    has_manual_heading = False
    for b in blocks:
        bt = b.get("type", "")
        if bt in ("heading_1", "heading_2", "heading_3"):
            text_parts = b.get(bt, {}).get("rich_text", [])
            heading_txt = "".join(t.get("plain_text", "") for t in text_parts).strip().lower()
            if heading_txt and heading_txt not in AUTO_HEADINGS:
                has_manual_heading = True
                break
    return not has_manual_heading

def set_pillar_talking_head(page_id: str) -> bool:
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=HEADERS, timeout=30,
                       json={"properties": {"Pillar": {"select": {"name": "Talking-Head"}}}})
    return r.status_code in (200, 201)

def main():
    if not NOTION_API_KEY:
        print("NOTION_API_KEY not set."); sys.exit(1)
    pages = fetch_blank_pillar_pages()
    print(f"   {len(pages)} page(s) have blank Pillar + Post Link set")
    flipped = skipped = 0
    for pid, title in pages:
        if page_is_noah_solo(pid):
            ok = set_pillar_talking_head(pid)
            print(f"   {'OK' if ok else 'FAIL'}  {title}  → Talking-Head")
            flipped += 1 if ok else 0
        else:
            print(f"   SKIP  {title}  (manual script body present)")
            skipped += 1
    print(f"\n   Flipped {flipped} → Talking-Head | Skipped {skipped} (need manual tagging)")

if __name__ == "__main__":
    main()
