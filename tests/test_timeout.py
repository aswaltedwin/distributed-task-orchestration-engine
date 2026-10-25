import time
import os
import threading
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_timeout.db"
os.environ["API_KEY"] = "supersecret"

from app.database import Base, engine, SessionLocal
from app.models import Task, TaskStatus
from app.worker import process_task

@patch("app.worker.queue")
def test_hard_timeout(mock_q):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # 1. Create task with 3s timeout
    task_id = "timeout-test"
    # Ensure task exists
    existing = db.get(Task, task_id)
    if existing:
        db.delete(existing)
        db.commit()

    db.add(Task(id=task_id, task_type="infinite_loop", status=TaskStatus.QUEUED, timeout=3))
    db.commit()
    
    # 2. Run process_task
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    
    start_t = time.time()
    process_task(task_id, sem)
    duration = time.time() - start_t
    
    # 3. Verification
    db.expire_all()
    task = db.get(Task, task_id)
    print(f"Task status: {task.status}")
    print(f"Last error: {task.last_error}")
    print(f"Duration: {duration:.2f}s")
    
    # It might be in SCHEDULED if it failed and triggered retry
    assert task.status in [TaskStatus.FAILED, TaskStatus.SCHEDULED]
    assert "TimeoutError" in task.last_error or "exceeded hard limit" in task.last_error
    assert 3.0 <= duration <= 6.0
    
    print("Verification passed: Hard timeout enforcement successfully killed the rogue subprocess.")

if __name__ == "__main__":
    # Clean up once in main
    if os.path.exists("test_timeout.db"):
        try:
            os.remove("test_timeout.db")
        except: pass
    test_hard_timeout()
