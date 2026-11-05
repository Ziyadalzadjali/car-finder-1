# ==============================================================================
# MASTER RUNNER & MULTI-PROCESS ENGINE (run_all.py)
# ==============================================================================
import multiprocessing
import subprocess
import sys
import time
import os

def run_worker(script_name):
    """Executes an individual worker script."""
    subprocess.run([sys.executable, script_name])

if __name__ == "__main__":
    print("[*] ALPHA initializing multi-process distributed crawler suite...")
    
    workers = [
        "worker_range_1.py",
        "worker_range_2.py",
        "worker_live_stream.py",
        "worker_monitor.py"
    ]
    
    # Ensure all worker files exist before launching
    for w in workers:
        if not os.path.exists(w):
            print(f"[-] Missing worker file: {w}. Generating...")
            # We will create them below if needed
            
    processes = []
    for script in workers:
        p = multiprocessing.Process(target=run_worker, args=(script,))
        processes.append(p)
        p.start()
        print(f"[+] Launched {script} [PID: {p.pid}]")
        
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("[!] Termination signal received. Shutting down workers gracefully, dammit.")
        for p in processes:
            p.terminate()