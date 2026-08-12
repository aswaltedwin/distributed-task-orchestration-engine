import time
import os
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 1. Environment Setup
os.environ["DATABASE_URL"] = "sqlite:///validation_metrics.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("validation_metrics.db"):
    os.remove("validation_metrics.db")

from app.database import Base, engine, SessionLocal
from app.main import app
from app.models import Task, TaskStatus
from app.worker import process_task, TASK_REGISTRY

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

# 2. Cooperative Task Handler for T7
def cooperative_handler(payload):
    # Simulate a long-running task with cancellation checks
    for i in range(10):
        # We need to reach back to DB to check cancel_requested
        with SessionLocal() as db:
            # We don't have task_id here normally, but in our engine 
            # we should probably pass it or use a thread local.
            # For this test, we'll find the task by type (mocking behavior)
            task = db.query(Task).filter(Task.task_type == "cooperative").first()
            if task and task.cancel_requested:
                return "CANCELLED"
        time.sleep(1)

def success_handler(payload): pass
def fail_handler(payload): raise ValueError("Fail")

@patch("app.worker.queue")
@patch("app.main.queue")
def test_cancellation_and_metrics(mock_main_q, mock_worker_q):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    TASK_REGISTRY["cooperative"] = cooperative_handler
    TASK_REGISTRY["success"] = success_handler
    TASK_REGISTRY["fail"] = fail_handler

    print("--- TEST T7: Running Cancellation ---")
    # Submit cooperative task
    resp = client.post("/tasks", json={"task_type": "cooperative", "payload": {}}, headers=headers)
    c_id = resp.json()["task_id"]
    
    # Run in thread
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    worker_thread = threading.Thread(target=process_task, args=(c_id, sem))
    worker_thread.start()
    
    time.sleep(1) # Allow it to start
    # Cancel it
    client.post(f"/tasks/{c_id}/cancel", headers=headers)
    worker_thread.join(timeout=5)
    
    task = db.query(Task).get(c_id)
    print(f"Task status: {task.status}, Cancel Requested: {task.cancel_requested}")
    t7_pass = task.status == TaskStatus.CANCELLED and task.cancel_requested == True

    print("\n--- TEST T12: Metrics Integrity ---")
    # Controlled sequence:
    # 1. 2 Successes
    # 2. 1 Failure (with 1 retry)
    # Already had 1 Cancelled from T7.
    
    # Success 1
    resp = client.post("/tasks", json={"task_type": "success", "payload": {}}, headers=headers)
    sem.acquire()
    process_task(resp.json()["task_id"], sem)
    
    # Success 2
    resp = client.post("/tasks", json={"task_type": "success", "payload": {}}, headers=headers)
    sem.acquire()
    process_task(resp.json()["task_id"], sem)
    
    # Failure + 1 Retry
    resp = client.post("/tasks", json={"task_type": "fail", "payload": {}}, headers=headers)
    f_id = resp.json()["task_id"]
    sem.acquire()
    process_task(f_id, sem) # Attempt 1
    
    # Check metrics via endpoint
    resp = client.get("/metrics", headers=headers)
    metrics = resp.text
    print(metrics)
    
    # Counts: 
    # T7: 1 submitted, 1 cancelled
    # Seq: 3 submitted, 2 success, 1 failed, 1 retried
    # Total: 4 submitted, 2 success, 1 failed, 1 retried, 1 cancelled
    
    t12_pass = (
        "tasks_submitted_total 4.0" in metrics and
        "tasks_success_total 2.0" in metrics and
        "tasks_failed_total 1.0" in metrics and
        "tasks_retried_total 1.0" in metrics and
        "tasks_cancelled_total 1.0" in metrics and
        "tasks_active 0.0" in metrics
    )

    print(f"\nRESULTS:\nT7_CANCELLATION: {'PASS' if t7_pass else 'FAIL'}")
    print(f"T12_METRICS: {'PASS' if t12_pass else 'FAIL'}")

if __name__ == "__main__":
    test_cancellation_and_metrics()
