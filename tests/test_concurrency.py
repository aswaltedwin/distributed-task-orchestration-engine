import time
import os
import threading
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.worker import run_worker, shutdown_event

# Setup file-based SQLite for testing
DB_FILE = "test_concurrency_v2.db"
try:
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
except Exception:
    pass

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def slow_handler(payload):
    print(f"[{threading.current_thread().name}] Task {payload['id']} starting 5s work...")
    time.sleep(5)
    print(f"[{threading.current_thread().name}] Task {payload['id']} finished.")

@patch("app.worker.SessionLocal", TestingSessionLocal)
@patch("app.worker.queue")
def test_parallel_execution(mock_queue):
    # 1. Prepare Database
    Base.metadata.all_meta = Base.metadata
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    task_ids = ["task-1", "task-2", "task-3"]
    for tid in task_ids:
        db.add(Task(id=tid, task_type="generate_report", payload={"id": tid}, status=TaskStatus.QUEUED))
    db.commit()

    # 2. Mock Redis to return 3 tasks then stop
    # We clear and use shutdown_event to cleanly stop the dispatcher loop.
    shutdown_event.clear()
    
    calls = list(task_ids)
    def reserve_side_effect(*args, **kwargs):
        if len(calls) > 0:
            return calls.pop(0)
        shutdown_event.set()
        return None

    mock_queue.reserve.side_effect = reserve_side_effect

    # 3. Start Dispatcher
    start_time = time.time()
    print(f"\nStarting parallel test at {start_time}")
    
    run_worker()
    
    end_time = time.time()
    duration = end_time - start_time
    print(f"Test finished after {duration:.2f} seconds.")

    # 4. Assertions
    db = TestingSessionLocal()
    tasks = db.query(Task).all()
    statuses = [t.status for t in tasks]
    print(f"Task statuses: {statuses}")

    assert all(s == TaskStatus.SUCCESS for s in statuses)
    # If serial, would take 15s+. Parallel should be ~5-7s.
    assert duration < 12 
    print("Verification passed: Tasks executed in parallel.")

if __name__ == "__main__":
    test_parallel_execution()
