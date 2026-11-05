# ==============================================================================
# WORKER 4: 24/7 Deal Monitor & Status Updater (worker_monitor.py)
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
    print("[Worker 4] 24/7 Monitor active tracking modifications and deletions...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    while True:
        db = load_db()
        modified = False
        for item in db:
            url = item.get('url')
            if not url or url == "N/A":
                continue
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status != 200:
                        if item.get('status') != 'deleted':
                            item['status'] = 'deleted'
                            modified = True
            except:
                if item.get('status') != 'deleted':
                    item['status'] = 'deleted'
                    modified = True
            time.sleep(1)
            
        if modified:
            save_atomic(db)
            print("[Worker 4] Database updated with status modifications.")
        time.sleep(300)

if __name__ == "__main__":
    run()