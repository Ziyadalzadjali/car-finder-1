# ==============================================================================
# WORKER 3: 24/7 New Deal Stream Ingestor (worker_live_stream.py)
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
    print("[Worker 3] 24/7 Live stream ingestor active, scanning for fresh uploads...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    while True:
        try:
            url = "https://sooq-cars.com/om/en/ready"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    db = load_db()
                    existing_ids = {item.get('id') for item in db}
                    # Dummy check for new incoming IDs from feed
                    # Insert logic for newly discovered listings
                    save_atomic(db)
        except Exception as e:
            print(f"[Worker 3] Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    run()