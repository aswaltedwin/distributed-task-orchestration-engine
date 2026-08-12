import subprocess
import time
import requests
import json

API_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": "supersecret"}

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()

def test_chaos():
    print("--- Starting Distributed Chaos Test ---")
    
    # 1. Clean and Start Cluster
    print("Stopping previous containers...")
    subprocess.run("docker-compose down -v", shell=True, stdout=subprocess.DEVNULL)
    
    print("Building and starting cluster...")
    subprocess.run("docker-compose up -d --build", shell=True, stdout=subprocess.DEVNULL)
    
    # Wait for healthchecks
    print("Waiting for cluster to stabilize (30s)...")
    time.sleep(30)

    # 2. Test A: Worker Death during execution
    print("\n[Test A] Worker Death Recovery")
    
    # Submit 10 slow tasks
    task_ids = []
    for i in range(10):
        resp = requests.post(f"{API_URL}/tasks", json={
            "task_type": "chaos_sleep",
            "payload": {"id": i}
        }, headers=HEADERS)
        task_ids.append(resp.json()["task_id"])
    
    print(f"Submitted 10 tasks. Waiting for assignment...")
    time.sleep(5)

    # Identify worker container for one task
    sample_tid = task_ids[0]
    resp = requests.get(f"{API_URL}/tasks/{sample_tid}", headers=HEADERS)
    worker_id = resp.json().get("claimed_by")
    print(f"Task {sample_tid} claimed by worker: {worker_id}")

    # Find container name for this worker
    # Docker compose workers are usually distributed-task-engine-worker-1, etc.
    # We'll just kill ONE worker container randomly if we can't map ID easily
    print("Killing one worker container...")
    subprocess.run("docker kill distributed-task-engine-worker-1", shell=True)
    
    # 3. Monitor Recovery
    print("Waiting for reaper to detect stale task (15s)...")
    time.sleep(15)
    
    resp = requests.get(f"{API_URL}/tasks/{sample_tid}", headers=HEADERS)
    new_status = resp.json().get("status")
    new_worker = resp.json().get("claimed_by")
    
    print(f"Task {sample_tid} Status: {new_status}")
    print(f"New Worker: {new_worker}")
    
    if new_status in ["RUNNING", "SUCCESS"] and new_worker != worker_id:
        print("SUCCESS: Task recovered and reclaimed by another worker.")
    else:
        print("FAILURE: Task not recovered correctly.")

    # 4. Test B: Priority Preemption
    print("\n[Test B] Priority Preemption")
    
    # Flood LOW queue
    print("Flooding LOW queue with 20 tasks...")
    for i in range(20):
        requests.post(f"{API_URL}/tasks", json={
            "task_type": "chaos_sleep",
            "payload": {"p": "low"},
            "priority": "LOW"
        }, headers=HEADERS)
    
    time.sleep(2)
    
    # Submit 1 HIGH task
    resp = requests.post(f"{API_URL}/tasks", json={
        "task_type": "echo",
        "payload": {"p": "high"},
        "priority": "HIGH"
    }, headers=HEADERS)
    high_tid = resp.json()["task_id"]
    print(f"Submitted HIGH task: {high_tid}")
    
    # Should be picked up immediately (preempting the waiting LOW tasks)
    time.sleep(5)
    resp = requests.get(f"{API_URL}/tasks/{high_tid}", headers=HEADERS)
    if resp.json().get("status") in ["RUNNING", "SUCCESS"]:
        print("SUCCESS: HIGH task preempted LOW tasks.")
    else:
        print(f"FAILURE: HIGH task status is {resp.json().get('status')}")

    # 5. Final Audit
    print("\n--- Chaos Test Complete ---")
    subprocess.run("docker-compose down -v", shell=True, stdout=subprocess.DEVNULL)

if __name__ == "__main__":
    test_chaos()
