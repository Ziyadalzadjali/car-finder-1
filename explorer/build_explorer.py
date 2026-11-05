"""Build explorer/sooq-cars-explorer.html from the cleaned listings.

Usage (from the repo root):
    python explorer/build_explorer.py [data/sooq_cars_dump_clean.json]
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "data", "sooq_cars_dump_clean.json")

with open(SRC, encoding="utf-8") as f:
    listings = json.load(f)

rows = []
for x in listings:
    slug = x["url"].split("/cars/", 1)[1].split("-", 1)[1]
    rows.append([int(x["listing_id"]), x["year"], html.escape(x["make"]), html.escape(x["model_trim"]),
                 x["price"], x["price_history"], x["times_seen"], slug])

data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
    page = f.read().replace("__DATA__", data)
with open(os.path.join(HERE, "sooq-cars-explorer.html"), "w", encoding="utf-8") as f:
    f.write(page)
print(f"Wrote {len(rows)} listings to explorer/sooq-cars-explorer.html")
