import time
import os
import threading
import concurrent.futures
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 1. Environment Setup
os.environ["DATABASE_URL"] = "sqlite:///stress_test.db"
os.environ["API_KEY"] = "supersecret"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

if os.path.exists("stress_test.db"):
    os.remove("stress_test.db")

from app.database import Base, engine, SessionLocal
from app.main import app
from app.models import Task, TaskStatus
from app.worker import process_task, TASK_REGISTRY

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

def fast_handler(payload):
    time.sleep(0.1) # 100ms task

@patch("app.worker.queue")
@patch("app.main.queue")
def run_stress_test(mock_main_q, mock_worker_q):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    TASK_REGISTRY["fast"] = fast_handler
    
    TOTAL_TASKS = 100
    CONCURRENCY = 5
    
    print(f"--- STARTING STRESS TEST: {TOTAL_TASKS} tasks, Concurrency: {CONCURRENCY} ---")
    
    # 1. Submission phase
    sub_start = time.time()
    task_ids = []
    for i in range(TOTAL_TASKS):
        resp = client.post("/tasks", json={"task_type": "fast", "payload": {}}, headers=headers)
        task_ids.append(resp.json()["task_id"])
    sub_duration = time.time() - sub_start
    print(f"Submission complete: {sub_duration:.2f}s ({TOTAL_TASKS/sub_duration:.2f} tasks/sec)")
    
    # 2. Execution phase
    # We'll use a ThreadPoolExecutor to simulate the worker's pool
    exec_start = time.time()
    semaphore = threading.BoundedSemaphore(CONCURRENCY)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = []
        for tid in task_ids:
            semaphore.acquire()
            futures.append(executor.submit(process_task, tid, semaphore))
        
        concurrent.futures.wait(futures)
    
    exec_duration = time.time() - exec_start
    throughput = TOTAL_TASKS / exec_duration
    
    # 3. Validation
    success_count = db.query(Task).filter(Task.status == TaskStatus.SUCCESS).count()
    
    print("\n--- STRESS TEST RESULTS ---")
    print(f"Total Tasks: {TOTAL_TASKS}")
    print(f"Success Count: {success_count}")
    print(f"Total Execution Time: {exec_duration:.2f}s")
    print(f"Throughput: {throughput:.2f} tasks/sec")
    print(f"Efficiency: {throughput/CONCURRENCY:.2f} tasks/sec per worker")
    
    # Theoretical min time for 100 tasks of 0.1s with 5 workers:
    # (100 * 0.1) / 5 = 2.0s
    # Plus overhead.
    
    assert success_count == TOTAL_TASKS
    print("\nSTRESS TEST: PASS")

if __name__ == "__main__":
    run_stress_test()
