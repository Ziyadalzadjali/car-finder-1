"""Polite full scanner for sooq-cars.com used-car listings (Oman by default).

How it works
  1. pages   - walks the numbered results pages (/om/en/ready/cars?page=N,
               20 cars each, allowed by the site's robots.txt) and records
               every listing ID with its card price and title.
  2. details - opens each listing's own page once and saves its specs
               (odometer, fuel, region, seller, colors, ...).
  3. export  - writes CSV + JSON from the database.

Everything is stored in SQLite (cars.db), keyed by listing ID, so a crash
or Ctrl+C loses nothing and the next run resumes. Price changes are kept in
a price history table. Standard library only, single connection, one
request at a time with a delay between requests.

Usage
  python scanner.py pages            # full index crawl (resumes if stopped)
  python scanner.py details          # fetch specs for listings without them
  python scanner.py export           # data/sooq_cars_full.csv / .json
  python scanner.py all              # pages + details + export
  python scanner.py stats            # what's in the database
Common options: --db cars.db --delay 1.5 --country om
"""
import argparse
import csv
import datetime as dt
import gzip
import html
import http.client
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

BASE = "https://sooq-cars.com"
USER_AGENT = "car-finder/1.0 (+https://github.com/Ziyadalzadjali/car-finder-1)"
RETRY_WAITS = [5, 15, 45, 120]          # seconds between retries
MAX_CONSECUTIVE_FAILURES = 5            # stop the run after this many

# Detail-page labels -> column names
SPEC_FIELDS = {
    "Odometer": "odometer", "Deal Type": "deal_type", "Body type": "body_type",
    "Cylinders": "cylinders", "Transmission": "transmission", "Key": "number_of_keys",
    "Options": "options", "Drive Line": "drive_type", "Fuel Type": "fuel_type",
    "Exterior Color": "exterior_color", "Interior Color": "interior_color",
    "Published Date": "published_date", "Region": "region", "Specs": "specs",
}
COLUMNS = ["listing_id", "url", "title", "year", "make", "model", "trim", "price", "currency",
           "status", "first_seen", "last_seen", "card_posted", "details_at",
           *SPEC_FIELDS.values(), "published_iso", "seller", "photos", "availability", "extra"]

# "7,900 OMR TOYOTA AVALON LIMITED 2019 19 minutes ago" or "Ask for price! KIA SELTOS SX 2026 24 minutes ago"
CARD_RE = re.compile(r"^(?:(?P<price>[\d,]+)\s+(?P<cur>[A-Z]{3})|Ask for price!)\s+"
                     r"(?P<name>.+?\s(?:19|20)\d{2})\s+(?P<ago>.+?ago|just now)\b")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- database
def open_db(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    cols = ",\n".join(f"{c} TEXT" for c in COLUMNS if c not in ("listing_id", "year", "price", "photos"))
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS listings (
        listing_id INTEGER PRIMARY KEY, year INTEGER, price INTEGER, photos INTEGER,
        last_seen_run INTEGER,
        {cols});
    CREATE TABLE IF NOT EXISTS prices (
        listing_id INTEGER, price INTEGER, seen_at TEXT, source TEXT);
    CREATE INDEX IF NOT EXISTS prices_id ON prices(listing_id);
    CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, started TEXT, finished TEXT,
        last_page INTEGER DEFAULT 0, listings_seen INTEGER DEFAULT 0);
    """)
    return db


def record_price(db, lid, price, source):
    if price is None:
        return
    row = db.execute("SELECT price FROM prices WHERE listing_id=? ORDER BY rowid DESC LIMIT 1", (lid,)).fetchone()
    if row is None or row["price"] != price:
        db.execute("INSERT INTO prices VALUES (?,?,?,?)", (lid, price, now(), source))


# ---------------------------------------------------------------- fetching
class Fetcher:
    def __init__(self, delay):
        self.delay = delay
        self.last = 0.0
        self.failures = 0
        self.requests = 0

    def get(self, url):
        """Return (status, text). status 404 is returned, other errors retried."""
        for attempt in range(len(RETRY_WAITS) + 1):
            wait = self.delay - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
                                                       "Accept": "text/html", "Accept-Language": "en"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    self.failures = 0
                    return resp.status, body.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    self.failures = 0
                    return e.code, ""
                retry_after = e.headers.get("Retry-After", "")
                reason = f"HTTP {e.code}"
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as e:
                retry_after, reason = "", str(e)
            if attempt == len(RETRY_WAITS):
                break
            pause = int(retry_after) if retry_after.isdigit() else RETRY_WAITS[attempt]
            log(f"  {reason} on {url}, retrying in {pause}s")
            time.sleep(pause)
        self.failures += 1
        if self.failures >= MAX_CONSECUTIVE_FAILURES:
            raise SystemExit(f"Stopping: {self.failures} requests in a row failed. "
                             "The site may be blocking or down. Run again later to resume.")
        return None, ""


# ---------------------------------------------------------------- parsing
def strip_tags(fragment):
    fragment = re.sub(r"<(svg|script|style)\b.*?</\1>", " ", fragment, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_results_page(text, country):
    """Return {listing_id: card dict} for one results page."""
    pat = re.compile(rf'href="(/{country}/en/ready/cars/(\d+)-[a-z0-9-]+)"')
    hits = list(pat.finditer(text))
    cards = {}
    for i, m in enumerate(hits):
        lid = int(m.group(2))
        if lid in cards and cards[lid].get("price") is not None:
            continue
        if i > 0 and int(hits[i - 1].group(2)) == lid:
            continue  # second link of the same card; the first one's chunk covers it
        # A card links to itself more than once: take everything up to the next card's first link.
        j = i + 1
        while j < len(hits) and int(hits[j].group(2)) == lid:
            j += 1
        end = hits[j].start() if j < len(hits) else m.end() + 6000
        chunk = text[m.end():end]
        card_text = strip_tags(chunk[chunk.find(">") + 1:])
        card = {"url": BASE + m.group(1), "price": None, "currency": None, "title": None, "card_posted": None}
        cm = CARD_RE.match(card_text)
        if cm:
            card.update(price=int(cm["price"].replace(",", "")) if cm["price"] else None,
                        currency=cm["cur"], title=cm["name"], card_posted=cm["ago"])
        if lid not in cards or card["price"] is not None:
            cards[lid] = card
    return cards


class SpecParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pairs, self.cur, self.buf, self.skip = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("svg", "script", "style"):
            self.skip += 1
        if tag in ("dt", "dd"):
            self.cur, self.buf = tag, []

    def handle_endtag(self, tag):
        if tag in ("svg", "script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == self.cur:
            self.pairs.append((tag, " ".join("".join(self.buf).split())))
            self.cur = None

    def handle_data(self, data):
        if self.cur and not self.skip:
            self.buf.append(data + " ")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def split_name(name, make_slug, model_slug):
    """'TOYOTA LAND CRUISER VX.R 2020' + slugs -> (make, model, trim, year)."""
    m = re.search(r"\s((?:19|20)\d{2})$", name)
    year = int(m.group(1)) if m else None
    words = (name[:m.start()] if m else name).split()
    make = model = None
    k = 0
    for slug, field in ((make_slug, "make"), (model_slug, "model")):
        if not slug:
            break
        for j in range(k + 1, len(words) + 1):
            if slugify(" ".join(words[k:j])) == slug:
                if field == "make":
                    make = " ".join(words[k:j])
                else:
                    model = " ".join(words[k:j])
                k = j
                break
        else:
            break
    if make is None and words:
        make, k = words[0], 1
    return make, model, " ".join(words[k:]) or None, year


def parse_detail_page(text, country):
    out = {"extra": {}}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        types = data.get("@type") if isinstance(data, dict) else None
        if types and "Car" in (types if isinstance(types, list) else [types]):
            offer = data.get("offers") or {}
            out["title"] = data.get("name")
            out["price"] = offer.get("price")
            out["currency"] = offer.get("priceCurrency")
            out["availability"] = (offer.get("availability") or "").rsplit("/", 1)[-1] or None
            out["seller"] = (offer.get("seller") or {}).get("name")
            out["photos"] = len(data.get("image") or [])
    p = SpecParser()
    p.feed(text)
    label = None
    for tag, value in p.pairs:
        if tag == "dt":
            label = value
        elif label:
            col = SPEC_FIELDS.get(label)
            if col:
                out[col] = value or None
            else:
                out["extra"][label] = re.sub(r"\s+Copy$", "", value)  # drop copy-button text (VIN)
            label = None
    if out.get("published_date"):
        try:
            d, mth, y = (int(x) for x in out["published_date"].split("/"))
            out["published_iso"] = dt.date(y, mth, d).isoformat()
        except ValueError:
            pass
    mm = re.search(rf'href="/{country}/en/ready/cars/([a-z][a-z0-9-]*)/([a-z0-9-]+)"', text)
    if out.get("title"):
        out["make"], out["model"], out["trim"], out["year"] = split_name(
            out["title"], mm.group(1) if mm else None, mm.group(2) if mm else None)
    if isinstance(out.get("price"), str):
        out["price"] = int(float(out["price"].replace(",", "")))
    out["extra"] = json.dumps(out["extra"], ensure_ascii=False) if out["extra"] else None
    return out


# ---------------------------------------------------------------- commands
def cmd_pages(db, f, args):
    run = db.execute("SELECT * FROM runs WHERE finished IS NULL AND country=? ORDER BY run_id DESC LIMIT 1",
                     (args.country,)).fetchone()
    if run and not args.fresh:
        run_id, page = run["run_id"], run["last_page"] + 1
        log(f"Resuming crawl run {run_id} at page {page}")
    else:
        run_id = db.execute("INSERT INTO runs (country, started) VALUES (?,?)", (args.country, now())).lastrowid
        db.commit()
        page = 1
        log(f"Starting crawl run {run_id}")
    empty_streak, done = 0, 0
    while args.max_pages is None or done < args.max_pages:
        url = f"{BASE}/{args.country}/en/ready/cars" + (f"?page={page}" if page > 1 else "")
        status, text = f.get(url)
        cards = parse_results_page(text, args.country) if status == 200 else {}
        if status == 404 or (status == 200 and not cards):
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        ts = now()
        for lid, c in cards.items():
            db.execute("""INSERT INTO listings (listing_id, url, title, price, currency, card_posted,
                              status, first_seen, last_seen, last_seen_run)
                          VALUES (?,?,?,?,?,?, 'active', ?, ?, ?)
                          ON CONFLICT(listing_id) DO UPDATE SET
                              url=excluded.url, title=COALESCE(excluded.title, title),
                              price=COALESCE(excluded.price, price), currency=COALESCE(excluded.currency, currency),
                              card_posted=excluded.card_posted, status='active',
                              last_seen=excluded.last_seen, last_seen_run=excluded.last_seen_run""",
                       (lid, c["url"], c["title"], c["price"], c["currency"], c["card_posted"], ts, ts, run_id))
            record_price(db, lid, c["price"], "results")
        db.execute("UPDATE runs SET last_page=?, listings_seen=(SELECT COUNT(*) FROM listings WHERE last_seen_run=?) "
                   "WHERE run_id=?", (page, run_id, run_id))
        db.commit()
        done += 1
        if page % 25 == 0 or done == 1:
            seen = db.execute("SELECT listings_seen FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
            log(f"page {page}: {len(cards)} cars, {seen} unique this run")
        page += 1
    if args.max_pages is not None and done >= args.max_pages and empty_streak < 2:
        log(f"Stopped after {done} pages (--max-pages). Run again to continue from page {page}.")
        return
    db.execute("UPDATE runs SET finished=? WHERE run_id=?", (now(), run_id))
    gone = db.execute("UPDATE listings SET status='not_listed' WHERE status='active' AND last_seen_run<?",
                      (run_id,)).rowcount
    db.commit()
    seen = db.execute("SELECT listings_seen FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
    log(f"Crawl finished at page {page - 1}: {seen} listings seen, {gone} earlier listings no longer listed.")


def cmd_details(db, f, args):
    where = "status='active' AND details_at IS NULL"
    params = []
    if args.refresh_days is not None:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.refresh_days)).isoformat()
        where = "status='active' AND (details_at IS NULL OR details_at < ?)"
        params = [cutoff]
    todo = [r["listing_id"] for r in db.execute(
        f"SELECT listing_id FROM listings WHERE {where} ORDER BY listing_id DESC", params)]
    if args.limit:
        todo = todo[:args.limit]
    eta = len(todo) * args.delay / 3600
    log(f"{len(todo)} listings need details (about {eta:.1f} h at {args.delay}s per request)")
    for i, lid in enumerate(todo, 1):
        url = db.execute("SELECT url FROM listings WHERE listing_id=?", (lid,)).fetchone()["url"]
        status, text = f.get(url)
        if status in (404, 410):
            db.execute("UPDATE listings SET status='removed', details_at=? WHERE listing_id=?", (now(), lid))
        elif status == 200:
            d = parse_detail_page(text, args.country)
            d["details_at"] = now()
            cols = [c for c in d if c in COLUMNS]
            db.execute(f"UPDATE listings SET {', '.join(c + '=?' for c in cols)} WHERE listing_id=?",
                       [d[c] for c in cols] + [lid])
            if d.get("availability") and d["availability"] != "InStock":
                db.execute("UPDATE listings SET status='sold' WHERE listing_id=?", (lid,))
            record_price(db, lid, d.get("price"), "detail")
        db.commit()
        if i % 50 == 0 or i == len(todo):
            log(f"details {i}/{len(todo)}")


def cmd_export(db, args):
    rows = [dict(r) for r in db.execute(f"SELECT {', '.join(COLUMNS)} FROM listings ORDER BY listing_id")]
    hist = {}
    for r in db.execute("SELECT listing_id, price FROM prices ORDER BY rowid"):
        hist.setdefault(r["listing_id"], []).append(r["price"])
    for r in rows:
        h = hist.get(r["listing_id"], [])
        r["price_history"] = h if len(set(h)) > 1 else []
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out + ".json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    with open(args.out + ".csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS + ["price_history"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "price_history": " -> ".join(map(str, r["price_history"]))})
    log(f"Exported {len(rows)} listings to {args.out}.json and .csv")


def cmd_stats(db):
    q = lambda sql: db.execute(sql).fetchone()[0]
    print(f"listings:        {q('SELECT COUNT(*) FROM listings')}")
    for r in db.execute("SELECT status, COUNT(*) n FROM listings GROUP BY status"):
        print(f"  {r['status']:<14} {r['n']}")
    print(f"with details:    {q('SELECT COUNT(*) FROM listings WHERE details_at IS NOT NULL')}")
    print(f"price changes:   {q('SELECT COUNT(*) FROM (SELECT listing_id FROM prices GROUP BY listing_id HAVING COUNT(DISTINCT price)>1)')}")
    for r in db.execute("SELECT run_id, started, finished, last_page, listings_seen FROM runs ORDER BY run_id DESC LIMIT 3"):
        print(f"run {r['run_id']}: started {r['started']}, finished {r['finished'] or '(not yet)'}, "
              f"page {r['last_page']}, {r['listings_seen']} seen")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["pages", "details", "export", "all", "stats"])
    ap.add_argument("--db", default="cars.db", help="SQLite file (default cars.db)")
    ap.add_argument("--country", default="om", help="site country code: om, ae, qa, sa ... (default om)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests (default 1.5, minimum 1)")
    ap.add_argument("--max-pages", type=int, help="pages: stop after this many results pages")
    ap.add_argument("--fresh", action="store_true", help="pages: start a new crawl instead of resuming")
    ap.add_argument("--limit", type=int, help="details: fetch at most this many listings")
    ap.add_argument("--refresh-days", type=float, help="details: also refetch details older than this")
    ap.add_argument("--out", default=os.path.join("data", "sooq_cars_full"), help="export: output path prefix")
    args = ap.parse_args(argv)
    args.delay = max(1.0, args.delay)
    db = open_db(args.db)
    f = Fetcher(args.delay)
    try:
        if args.command in ("pages", "all"):
            cmd_pages(db, f, args)
        if args.command in ("details", "all"):
            cmd_details(db, f, args)
        if args.command in ("export", "all"):
            cmd_export(db, args)
        if args.command == "stats":
            cmd_stats(db)
    except KeyboardInterrupt:
        db.commit()
        log("Stopped. Progress is saved; run the same command again to resume.")
    finally:
        db.close()
        if f.requests:
            log(f"{f.requests} requests made")


if __name__ == "__main__":
    sys.exit(main())
