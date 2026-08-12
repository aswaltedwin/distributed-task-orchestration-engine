import subprocess
import time
import os
import sqlite3
from app.models import TaskPriority

# Configuration
DB_PATH = "multi_node.db"
API_PORT = 8001
API_KEY = "supersecret"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["API_KEY"] = API_KEY

def run_verify():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("--- Starting Multi-Node Verification ---")
    
    # 1. Start API Server
    api_proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)],
        env={**os.environ, "PYTHONPATH": "."},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3) # Wait for startup
    
    # 2. Start 3 Workers
    worker_procs = []
    for _ in range(3):
        p = subprocess.Popen(
            ["python", "-m", "app.worker"],
            env={**os.environ, "PYTHONPATH": "."},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        worker_procs.append(p)
    
    print(f"Cluster ready: 1 API + 3 Workers")

    try:
        # 3. Submit 30 tasks
        import requests
        headers = {"X-API-Key": API_KEY}
        task_ids = []
        for i in range(30):
            resp = requests.post(f"http://localhost:{API_PORT}/tasks", json={
                "task_type": "echo",
                "payload": {"msg": i}
            }, headers=headers)
            task_ids.append(resp.json()["task_id"])
        
        print(f"Submitted 30 tasks. Waiting for processing...")
        time.sleep(10)
        
        # 4. Check distribution in DB
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT claimed_by, COUNT(*) FROM tasks GROUP BY claimed_by")
        rows = cursor.fetchall()
        
        print("\nWorker Attribution Results:")
        workers_found = []
        for row in rows:
            wid = row[0]
            count = row[1]
            if wid:
                print(f"  Worker {wid}: {count} tasks")
                workers_found.append(wid)
            else:
                print(f"  Unclaimed tasks: {count}")
        
        # Verification: More than 1 worker should have processed tasks
        if len(workers_found) > 1:
            print(f"\nSUCCESS: Work distributed across {len(workers_found)} independent worker instances.")
        else:
            print("\nFAILURE: Work not distributed!")
            exit(1)

    finally:
        print("\nShutting down cluster...")
        api_proc.terminate()
        for w in worker_procs:
            w.terminate()
        api_proc.wait()
        for w in worker_procs:
            w.wait()

if __name__ == "__main__":
    run_verify()
