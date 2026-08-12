import time
import os
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 1. Environment Setup
os.environ["DATABASE_URL"] = "sqlite:///full_validation_v2.db"
os.environ["API_KEY"] = "supersecret"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

try:
    if os.path.exists("full_validation_v2.db"):
        os.remove(os.path.exists("full_validation_v2.db") and "full_validation_v2.db" or "")
except Exception:
    pass

from app.database import Base, engine, SessionLocal
from app.main import app
from app.models import Task, TaskStatus
from app.worker import process_task
from app.reaper import run_reaper
from app.scheduler import run_scheduler
from app.sweeper import run_sweeper

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

def run_validation():
    print("=== STARTING FULL SYSTEM VALIDATION (UTC FIX) ===\n")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    results = {}

    # Use a shared mock for all tests to avoid isolation issues
    with patch("app.main.queue") as mock_main_q, \
         patch("app.worker.queue") as mock_worker_q:

        # TEST 1: Happy Path
        print("TEST 1: Happy Path...")
        resp = client.post("/tasks", json={"task_type": "echo", "payload": {}}, headers=headers)
        task_id = resp.json()["task_id"]
        sem = threading.BoundedSemaphore(1)
        sem.acquire()
        process_task(task_id, sem)
        task = db.query(Task).get(task_id)
        results["T1_HAPPY_PATH"] = task.status == TaskStatus.SUCCESS

        # TEST 2: Concurrency
        print("TEST 2: Concurrency...")
        start = time.time()
        c_ids = [client.post("/tasks", json={"task_type": "send_email", "payload": {}}, headers=headers).json()["task_id"] for _ in range(3)]
        sem_c = threading.BoundedSemaphore(3)
        threads = []
        for tid in c_ids:
            sem_c.acquire()
            t = threading.Thread(target=process_task, args=(tid, sem_c))
            t.start()
            threads.append(t)
        for t in threads: t.join()
        duration = time.time() - start
        results["T2_CONCURRENCY"] = duration < 10
        print(f"  Duration: {duration:.2f}s")

        # TEST 3: Retry + DLQ
        print("TEST 3: Retry + DLQ...")
        f_id = client.post("/tasks", json={"task_type": "fail", "payload": {}}, headers=headers).json()["task_id"]
        for _ in range(4): # 1 + 3 retries
            with SessionLocal() as s_db:
                task = s_db.query(Task).get(f_id)
                task.status = TaskStatus.QUEUED
                s_db.commit()
            sem.acquire()
            process_task(f_id, sem)
        task = db.query(Task).get(f_id)
        results["T3_RETRY_DLQ"] = task.status == TaskStatus.DEAD_LETTER

        # TEST 4: Reaper (Using utcnow)
        print("TEST 4: Reaper...")
        c_id = "reaper-task"
        db.add(Task(id=c_id, task_type="echo", status=TaskStatus.RUNNING, heartbeat_at=datetime.utcnow() - timedelta(seconds=60)))
        db.commit()
        with patch("app.reaper.SessionLocal", SessionLocal), patch("app.reaper.queue", mock_worker_q), patch("time.sleep", side_effect=InterruptedError):
            try: run_reaper(threshold_seconds=15)
            except InterruptedError: pass
        db.refresh(db.query(Task).get(c_id))
        results["T4_REAPER"] = db.query(Task).get(c_id).status == TaskStatus.QUEUED

        # TEST 5: Sweeper (Using utcnow)
        print("TEST 5: Sweeper...")
        s_id = "sweeper-task"
        # We manually set updated_at to be old
        old_time = datetime.utcnow() - timedelta(seconds=60)
        db.add(Task(id=s_id, task_type="echo", status=TaskStatus.QUEUED, updated_at=old_time))
        db.commit()
        # Force the DB to keep the old updated_at (SQLAlchemy might auto-update it on commit)
        db.execute(Base.metadata.tables['tasks'].update().where(Task.id == s_id).values(updated_at=old_time))
        db.commit()
        
        with patch("app.sweeper.SessionLocal", SessionLocal), patch("app.sweeper.queue", mock_worker_q), patch("time.sleep", side_effect=InterruptedError):
            try: run_sweeper(threshold_seconds=15)
            except InterruptedError: pass
        assert any(c[0] == "enqueue" and c[1][0] == s_id for c in mock_worker_q.mock_calls)
        results["T5_SWEEPER"] = True

        # TEST 6: Scheduling
        print("TEST 6: Scheduling...")
        # Create a task that is due NOW
        past_time = datetime.now() - timedelta(seconds=1)
        resp = client.post("/tasks", json={"task_type": "echo", "payload": {}, "run_at": past_time.isoformat()}, headers=headers)
        # Note: API might set it to QUEUED immediately if it sees past time.
        # So let's create a future one, verify SCHEDULED, then update DB to make it past due.
        future = datetime.now() + timedelta(hours=1)
        resp = client.post("/tasks", json={"task_type": "echo", "payload": {}, "run_at": future.isoformat()}, headers=headers)
        sch_id = resp.json()["task_id"]
        
        task = db.query(Task).get(sch_id)
        is_init_scheduled = task.status == TaskStatus.SCHEDULED
        
        # Manually make it past due
        db.execute(Base.metadata.tables['tasks'].update().where(Task.id == sch_id).values(run_at=datetime.now() - timedelta(seconds=10)))
        db.commit()
        
        with patch("app.scheduler.SessionLocal", SessionLocal), patch("app.scheduler.queue", mock_worker_q), patch("time.sleep", side_effect=InterruptedError):
            try: run_scheduler()
            except InterruptedError: pass
            
        task = db.query(Task).get(sch_id)
        results["T6_SCHEDULING"] = is_init_scheduled and task.status == TaskStatus.QUEUED
        print(f"  Status: {task.status}")

        # TEST 9/10: Auth/RateLimit
        print("TEST 9/10: Security...")
        results["T9_AUTH"] = client.post("/tasks", json={}).status_code == 401
        with patch("app.main.settings.RATE_LIMIT_PER_MINUTE", 2):
            # Mock redis.incr to return 1, 2, 3
            mock_main_q.redis.incr.side_effect = [1, 2, 3]
            client.get("/metrics", headers=headers)
            client.get("/metrics", headers=headers)
            results["T10_RATELIMIT"] = client.get("/metrics", headers=headers).status_code == 429

    # --- REPORT ---
    print("\n=== VALIDATION REPORT ===")
    all_pass = True
    for test, passed in results.items():
        print(f"{test}: {'PASS' if passed else 'FAIL'}")
        if not passed: all_pass = False
    
    if all_pass: print("\nALL TESTS PASSED")
    else: exit(1)

if __name__ == "__main__":
    run_validation()
