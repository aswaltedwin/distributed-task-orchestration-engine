import time
import os
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.worker import process_task

# Setup file-based SQLite
DB_FILE = "test_backoff.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def fail_handler(payload):
    raise ValueError("Retry me")

@patch("app.worker.SessionLocal", TestingSessionLocal)
@patch("app.worker.queue")
@patch("app.worker.TASK_REGISTRY", {"fail": fail_handler})
def test_backoff_logic(mock_queue):
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # 1. Create task
    task_id = "backoff-test"
    db.add(Task(id=task_id, task_type="fail", status=TaskStatus.QUEUED))
    db.commit()
    
    # 2. Run process_task (Attempt 1)
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    process_task(task_id, sem)
    
    # 3. Verification
    task = db.get(Task, task_id)
    print(f"Status after fail 1: {task.status}")
    print(f"Retry count: {task.retry_count}")
    print(f"Run at: {task.run_at}")
    
    # After fail 1, retry_count=1. Backoff = 5 * (2^(1-1)) = 5s
    now = datetime.utcnow()
    assert task.status == TaskStatus.SCHEDULED
    assert task.retry_count == 1
    assert task.run_at > now + timedelta(seconds=3) # Allow jitter (5s +/- 1s)
    
    # 4. Run again (Attempt 2)
    # We must manually reset to QUEUED to simulate scheduler promotion
    task.status = TaskStatus.QUEUED
    db.commit()
    
    sem.acquire()
    process_task(task_id, sem)
    
    task = db.get(Task, task_id)
    print(f"Status after fail 2: {task.status}")
    print(f"Retry count: {task.retry_count}")
    # After fail 2, retry_count=2. Backoff = 5 * (2^(2-1)) = 10s
    assert task.retry_count == 2
    assert task.run_at > now + timedelta(seconds=7) # Allow jitter (10s +/- 2s)
    
    print("Verification passed: Exponential backoff correctly scheduled.")

if __name__ == "__main__":
    test_backoff_logic()
