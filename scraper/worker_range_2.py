# ==============================================================================
# WORKER 2: ID Range 1,000,000 to 2,000,000 (worker_range_2.py)
# ==============================================================================
import urllib.request
import json
import os
import time

OUTPUT_FILE = "sooq_cars_master_database.json"

def save_atomic(data):
    temp_file = OUTPUT_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, OUTPUT_FILE)

def load_db():
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def run():
    print("[Worker 2] Scanning ID range 1,000,000 -> 2,000,000...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    seen_ids = set()
    db = load_db()
    for item in db:
        seen_ids.add(item.get('id'))
        
    for car_id in range(1000000, 2000000):
        if car_id in seen_ids:
            continue
            
        url = f"https://sooq-cars.com/om/en/ready/cars/{car_id}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    record = {"id": car_id, "url": url, "status": "active"}
                    db.append(record)
                    seen_ids.add(car_id)
                    save_atomic(db)
        except:
            pass
        time.sleep(0.1)

if __name__ == "__main__":
    run()