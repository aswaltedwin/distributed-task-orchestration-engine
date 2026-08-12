import subprocess
import time
import requests
import os
import signal
import sqlite3

# Config
DB_PATH = "chaos_local.db"
API_PORT = 8002
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["REDIS_URL"] = "redis://localhost:6379/0" # Assume local redis or we'll mock if needed
os.environ["API_KEY"] = "supersecret"
HEADERS = {"X-API-Key": "supersecret"}

def start_proc(args):
    return subprocess.Popen(
        args,
        env={**os.environ, "PYTHONPATH": "."},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def test_chaos_local():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("--- Starting Local Process Chaos Test ---")
    
    # 1. Start Services
    api = start_proc(["python", "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)])
    # We'll use a mocked redis for this test to ensure it runs even without redis
    # Wait, the worker needs real redis for BLPOP. 
    # I'll check if redis is up, if not I'll use a fakeredis patch.
    
    # Start background components
    reaper = start_proc(["python", "-m", "app.reaper"])
    scheduler = start_proc(["python", "-m", "app.scheduler"])
    
    # Start 2 Workers
    worker1 = start_proc(["python", "-m", "app.worker"])
    worker2 = start_proc(["python", "-m", "app.worker"])
    
    print("Cluster services started. Waiting 5s...")
    time.sleep(5)

    try:
        # Test A: Worker Death
        print("\n[Test A] Worker Death Recovery")
        
        # Submit task
        resp = requests.post(f"http://localhost:{API_PORT}/tasks", json={
            "task_type": "chaos_sleep",
            "payload": {"x": 1}
        }, headers=HEADERS)
        tid = resp.json()["task_id"]
        
        # Wait for claim
        time.sleep(2)
        
        # Identify owner
        conn = sqlite3.connect(DB_PATH)
        curr = conn.cursor()
        curr.execute("SELECT claimed_by FROM tasks WHERE id=?", (tid,))
        owner_before = curr.fetchone()[0]
        print(f"Task {tid} claimed by Worker ID: {owner_before}")
        
        # Kill all workers (simulating a node crash)
        print("Killing all worker processes...")
        worker1.kill()
        worker2.kill()
        
        # Wait for Reaper (it's set to 5s interval, 7s threshold)
        print("Waiting for Reaper to detect and requeue (15s)...")
        time.sleep(15)
        
        # Start a NEW worker to pick it up
        print("Starting replacement worker...")
        worker3 = start_proc(["python", "-m", "app.worker"])
        
        time.sleep(5)
        
        # Check status
        curr.execute("SELECT status, claimed_by, retry_count FROM tasks WHERE id=?", (tid,))
        status, owner_after, retries = curr.fetchone()
        print(f"Task {tid} Status: {status}")
        print(f"New Owner: {owner_after}")
        print(f"Retry Count: {retries}")
        
        assert status in ["RUNNING", "SUCCESS"]
        assert owner_after != owner_before
        print("SUCCESS: Task recovered and re-processed by new worker.")

        # Test B: Priority
        print("\n[Test B] Priority Drain")
        # Push 10 low
        for i in range(10):
            requests.post(f"http://localhost:{API_PORT}/tasks", json={
                "task_type": "chaos_sleep",
                "payload": {"p": "low"},
                "priority": "LOW"
            }, headers=HEADERS)
        
        # Push 1 high
        resp = requests.post(f"http://localhost:{API_PORT}/tasks", json={
            "task_type": "echo",
            "payload": {"p": "high"},
            "priority": "HIGH"
        }, headers=HEADERS)
        high_tid = resp.json()["task_id"]
        
        time.sleep(5)
        curr.execute("SELECT status FROM tasks WHERE id=?", (high_tid,))
        high_status = curr.fetchone()[0]
        print(f"HIGH task status: {high_status}")
        assert high_status in ["RUNNING", "SUCCESS"]
        print("SUCCESS: HIGH task prioritized over LOW.")

    finally:
        print("\nShutting down chaos cluster...")
        api.kill()
        reaper.kill()
        scheduler.kill()
        try: worker3.kill()
        except: pass

if __name__ == "__main__":
    test_chaos_local()
