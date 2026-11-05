"""Clean sooq_cars_infinite_scale_dump.json into one record per listing.

The dump is JSON Lines: each listing card was captured 3 times (full card,
short card, price only) and the infinite scroll re-served the same cards on
many pages. Only the full card carries the URL, so we keep those lines,
dedupe by listing ID, and parse price / make / year out of the text.

Usage: python clean_dump.py [input] [output_prefix]
Writes <prefix>.json and <prefix>.csv
"""
import csv
import json
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "sooq_cars_infinite_scale_dump.json"
OUT = sys.argv[2] if len(sys.argv) > 2 else "sooq_cars_dump_clean"
BASE = "https://sooq-cars.com"

MULTI_WORD_MAKES = ["LYNK & CO", "LAND ROVER", "ALFA ROMEO", "ASTON MARTIN", "ROLLS ROYCE",
                    "MERCEDES BENZ", "GREAT WALL", "RANGE ROVER"]
HEAD_RE = re.compile(r"^(?P<price>[\d,]+)\s+(?P<cur>[A-Z]{3})\s+(?P<name>.+?)\s+(?P<year>(19|20)\d{2})$")
URL_RE = re.compile(r"^/om/en/ready/cars/(\d+)-")


def split_make(name):
    upper = name.upper()
    for m in MULTI_WORD_MAKES:
        if upper.startswith(m + " ") or upper == m:
            return name[:len(m)], name[len(m):].strip()
    parts = name.split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


listings = {}
stats = {"lines": 0, "card_lines": 0, "unparsed": 0}
with open(SRC, encoding="utf-8") as f:
    for line in f:
        stats["lines"] += 1
        o = json.loads(line)
        url = o.get("url")
        if not url or url == "N/A":
            continue  # short-card / price-only duplicates
        stats["card_lines"] += 1
        m_id = URL_RE.match(url)
        head = o["raw_text"].split(" Clock ")[0].strip()
        m = HEAD_RE.match(head)
        lid = m_id.group(1) if m_id else url
        rec = listings.get(lid)
        if rec is None:
            rec = listings[lid] = {
                "listing_id": lid, "year": None, "make": None, "model_trim": None,
                "full_name": None, "price": None, "currency": None,
                "price_history": [], "url": BASE + url,
                "first_seen_page": o["page"], "last_seen_page": o["page"],
                "times_seen": 0, "raw_text": head,
            }
        rec["times_seen"] += 1
        rec["first_seen_page"] = min(rec["first_seen_page"], o["page"])
        rec["last_seen_page"] = max(rec["last_seen_page"], o["page"])
        if not m:
            stats["unparsed"] += 1
            continue
        price = int(m["price"].replace(",", ""))
        make, model_trim = split_make(m["name"])
        rec.update(year=int(m["year"]), make=make.upper(), model_trim=model_trim,
                   full_name=f'{m["name"]} {m["year"]}', currency=m["cur"],
                   price=price, raw_text=head)
        if not rec["price_history"] or rec["price_history"][-1] != price:
            rec["price_history"].append(price)

rows = sorted(listings.values(), key=lambda r: int(r["listing_id"]) if r["listing_id"].isdigit() else 0)
for r in rows:
    # price_history is in scroll order (page number), not a confirmed timeline
    if len(set(r["price_history"])) <= 1:
        r["price_history"] = []

with open(OUT + ".json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
cols = [k for k in rows[0] if k != "price_history"] + ["price_history"]
with open(OUT + ".csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({**r, "price_history": " -> ".join(map(str, r["price_history"]))})

stats["unique_listings"] = len(rows)
stats["price_changed"] = sum(1 for r in rows if r["price_history"])
stats["missing_parse"] = sum(1 for r in rows if r["price"] is None)
print(json.dumps(stats))
