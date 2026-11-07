"""Build explorer/sooq-cars-explorer.html from scanner or cleaner output.

Usage (from the repo root):
    python explorer/build_explorer.py                                   # data/sooq_cars_full.json (scanner export)
    python explorer/build_explorer.py data/sooq_cars_dump_clean.json    # older cleaned dump
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATA, "sooq_cars_full.json")
MULTI_WORD_MAKES = ["LYNK & CO", "LAND ROVER", "ALFA ROMEO", "ASTON MARTIN", "ROLLS ROYCE", "GREAT WALL"]


def split_title(title):
    """'TOYOTA LAND CRUISER VX.R 2020' -> ('TOYOTA', 'LAND CRUISER VX.R', 2020)."""
    m = re.search(r"\s((?:19|20)\d{2})$", title)
    year = int(m.group(1)) if m else None
    name = title[:m.start()] if m else title
    for mk in MULTI_WORD_MAKES:
        if name.upper().startswith(mk + " "):
            return mk, name[len(mk):].strip(), year
    parts = name.split(" ", 1)
    return parts[0].upper(), (parts[1] if len(parts) > 1 else ""), year


with open(SRC, encoding="utf-8") as f:
    listings = json.load(f)

full = listings and "status" in listings[0]
rows = []
for x in listings:
    slug = x["url"].split("/cars/", 1)[1].split("-", 1)[1]
    title = x.get("title") or x.get("full_name")
    if not title:  # "Ask for price" cards from before the scanner read their titles
        title = " ".join(w.upper() if not w.isdigit() else w for w in slug.split("-"))
    make, rest, year = split_title(title)
    if full and x.get("make"):
        make = x["make"].upper()
        rest = " ".join(p for p in (x.get("model"), x.get("trim")) if p) or rest
    gone = 0 if not full or x["status"] == "active" else 1
    rows.append([int(x["listing_id"]), x.get("year") or year, html.escape(make), html.escape(rest),
                 x.get("price"), x.get("price_history") or [], gone, slug, html.escape(x.get("region") or "")])

if full:
    detailed = sum(1 for x in listings if x.get("details_at"))
    meta = {"source": "Oman listings from the full site scan",
            "note": f"Region and other specs are filled for the {detailed:,} cars whose own page has been fetched so far. "
                    "\"Ask\" means the seller wrote \"Ask for price\". A price chip shows the earlier price when it changed "
                    "between scans. Sold or removed cars are hidden unless you change Status."}
else:
    meta = {"source": "listings from the cleaned scroll dump",
            "note": "A price chip shows the earlier asking price for listings that changed during the scrape (scroll order, not dated)."}

data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
    page = f.read().replace("__META__", json.dumps(meta, ensure_ascii=False)).replace("__DATA__", data)
with open(os.path.join(HERE, "sooq-cars-explorer.html"), "w", encoding="utf-8") as f:
    f.write(page)
print(f"Wrote {len(rows)} listings ({len(page) / 1e6:.1f} MB) to explorer/sooq-cars-explorer.html")
