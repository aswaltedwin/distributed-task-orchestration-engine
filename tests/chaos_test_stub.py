import subprocess
import time
import os
import requests
import signal
from concurrent.futures import ThreadPoolExecutor

# Config
API_URL = "http://localhost:8000"
API_KEY = "supersecret"
HEADERS = {"X-API-Key": API_KEY}
NUM_TASKS = 20

def start_worker():
    return subprocess.Popen(
        ["python", "-m", "app.worker"],
        env={**os.environ, "PYTHONPATH": "."},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def test_multi_node_distribution():
    print("Starting Multi-node Distribution Test...")
    
    # 1. Start 3 workers
    workers = [start_worker() for _ in range(3)]
    print(f"Launched {len(workers)} worker processes.")
    
    try:
        # 2. Submit tasks
        task_ids = []
        for i in range(NUM_TASKS):
            resp = requests.post(f"{API_URL}/tasks", json={
                "task_type": "echo",
                "payload": {"msg": f"task-{i}"}
            }, headers=HEADERS)
            task_ids.append(resp.json()["task_id"])
        
        print(f"Submitted {NUM_TASKS} tasks.")
        
        # 3. Wait for completion
        time.sleep(10)
        
        # 4. Audit distribution
        worker_counts = {}
        for tid in task_ids:
            resp = requests.get(f"{API_URL}/tasks/{tid}", headers=HEADERS)
            data = resp.json()
            wid = data.get("claimed_by", "unknown")
            worker_counts[wid] = worker_counts.get(wid, 0) + 1
            
        print("\nDistribution Audit:")
        for wid, count in worker_counts.items():
            print(f"  Worker {wid}: {count} tasks")
            
        assert len(worker_counts) > 1, "Only one worker processed tasks!"
        print("\nMulti-node distribution verified: SUCCESS")

    finally:
        print("Shutting down workers...")
        for w in workers:
            w.terminate()

if __name__ == "__main__":
    # This test requires a running API server
    # In this environment, we might need to mock the API or start it in background
    pass
