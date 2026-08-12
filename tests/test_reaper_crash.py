import time
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.reaper import run_reaper
from app.config import settings

# Setup file-based SQLite for testing
DB_FILE = "test_reaper.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@patch("app.reaper.SessionLocal", TestingSessionLocal)
@patch("app.reaper.queue")
def test_reaper_crash_recovery(mock_queue):
    # 1. Prepare Database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # 2. Simulate a CRASHED task
    # Status = RUNNING, but heartbeat is 60 seconds old
    stale_time = datetime.utcnow() - timedelta(seconds=60)
    task_id = "crashed-task-001"
    crashed_task = Task(
        id=task_id,
        task_type="test_task",
        payload={},
        status=TaskStatus.RUNNING,
        heartbeat_at=stale_time,
        retry_count=0
    )
    db.add(crashed_task)
    db.commit()
    
    print(f"Injected crashed task {task_id} with heartbeat from {stale_time}")

    # 3. Run Reaper for one iteration
    # We'll use a mock to stop the loop after one run
    with patch("time.sleep", side_effect=InterruptedError("Stop loop")):
        try:
            run_reaper(interval=1, threshold_seconds=15)
        except InterruptedError:
            print("Reaper iteration completed.")

    # 4. Verification
    db.refresh(crashed_task)
    print(f"Final Task Status: {crashed_task.status}")
    print(f"Final Retry Count: {crashed_task.retry_count}")
    print(f"Final Last Error: {crashed_task.last_error}")

    assert crashed_task.status == TaskStatus.QUEUED
    assert crashed_task.retry_count == 1
    assert crashed_task.heartbeat_at is None
    assert "Recovered stale task" in crashed_task.last_error
    
    # Verify Redis enqueue was called
    mock_queue.enqueue.assert_called_once_with(task_id, priority=crashed_task.priority)
    print("Verification passed: Task recovered and requeued.")

if __name__ == "__main__":
    test_reaper_crash_recovery()
