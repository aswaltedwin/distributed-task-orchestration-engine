import time
import threading
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.worker import run_worker, shutdown_event
from app.config import settings

import os

# Setup file-based SQLite for testing
DB_FILE = "test_worker.db"
try:
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
except Exception:
    pass

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def mock_handler(payload):
    print(f"Task executing with payload: {payload}")
    time.sleep(12)  # Long enough to trigger 2 heartbeats (at 5s and 10s)
    print("Task execution finished.")

@patch("app.worker.SessionLocal", TestingSessionLocal)
@patch("app.worker.queue")
def test_claim_and_heartbeat(mock_queue):
    # 1. Prepare Database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    task_id = "test-uuid-123"
    new_task = Task(
        id=task_id,
        task_type="chaos_sleep",
        payload={"duration": 12},
        status=TaskStatus.QUEUED
    )
    db.add(new_task)
    db.commit()
    
    # Capture the initial heartbeat_at
    db.refresh(new_task)
    initial_heartbeat = new_task.heartbeat_at

    # 2. Mock Redis Queue
    # We clear and use shutdown_event to cleanly stop the dispatcher loop.
    shutdown_event.clear()
    
    calls = [task_id]
    def reserve_side_effect(*args, **kwargs):
        if len(calls) > 0:
            return calls.pop(0)
        shutdown_event.set()
        return None

    mock_queue.reserve.side_effect = reserve_side_effect

    # 3. Run Worker in a thread so we can monitor it
    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()

    # 4. Monitor Heartbeat Changes
    print("\nMonitoring heartbeats...")
    heartbeat_changes = 0
    last_hb = initial_heartbeat
    
    # Check for 15 seconds (task takes 12s)
    for _ in range(15):
        time.sleep(1)
        db.refresh(new_task)
        if new_task.heartbeat_at != last_hb:
            heartbeat_changes += 1
            last_hb = new_task.heartbeat_at
            print(f"Heartbeat updated at: {last_hb}")

    # 5. Assertions
    db.refresh(new_task)
    print(f"\nFinal Task Status: {new_task.status}")
    print(f"Total Heartbeat Updates: {heartbeat_changes}")

    assert new_task.status == TaskStatus.SUCCESS
    assert heartbeat_changes >= 2  # At 5s and 10s
    assert new_task.retry_count == 0

if __name__ == "__main__":
    # Manual run if not using pytest
    test_claim_and_heartbeat()
