# car-finder

Car listings scraped from [sooq-cars.com](https://sooq-cars.com/om/en/ready) (Oman), cleaned into one row per listing, plus a page to search and filter them. Prices are in Omani rials (OMR).

## What's here

| Path | What it is |
|---|---|
| `clean_dump.py` | Turns the raw infinite-scroll dump into one record per listing |
| `data/sooq_cars_dump_clean.csv` / `.json` | 2,510 unique listings from the cleaned dump |
| `data/sooq_cars_sample.json` | 51 listings with full details (mileage, fuel, region, seller, colors) |
| `explorer/sooq-cars-explorer.html` | Search, filter and sort page. Open it in a browser |
| `explorer/template.html`, `explorer/build_explorer.py` | Rebuild the explorer page from the cleaned data |
| `scraper/` | First version of the multi-process scraper (see known issues) |

## Cleaning the raw dump

The raw dump (`sooq_cars_infinite_scale_dump.json`, ~247 MB, JSON Lines) is not in the repo because it is over GitHub's file size limit. Each listing card in it appears 3 times (full card, short card, price only), and the infinite scroll served the same cards on many pages: 1,976,764 lines hold only 2,510 unique listings.

```bash
python clean_dump.py sooq_cars_infinite_scale_dump.json data/sooq_cars_dump_clean
python explorer/build_explorer.py
```

Each cleaned record has `listing_id`, `year`, `make`, `model_trim`, `full_name`, `price`, `currency`, `price_history` (only when the price changed), `url`, `first_seen_page`, `last_seen_page`, `times_seen` and `raw_text`.

Limits: model and trim stay in one field, because the cards don't mark where one ends; the cards only say "1 minute ago", so there's no posting date; mileage, region and seller are only on each listing's own page.

## Known issues in `scraper/`

- All four workers rewrite the same `sooq_cars_master_database.json`, so they overwrite each other's results.
- The ID range workers scan 1 to 2,000,000, but live listing IDs are around 1,617,000 to 2,389,000.
- Only `{id, url, status}` is saved; no car details are parsed.
- `worker_live_stream.py` has no logic to add new listings yet.
- Errors are silently ignored, and four non-stop processes put heavy load on the site.

Check sooq-cars.com's `robots.txt` and terms of use before running any scraper.
