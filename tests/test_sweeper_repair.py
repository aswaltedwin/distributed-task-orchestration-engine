import time
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.sweeper import run_sweeper

# Setup file-based SQLite for testing
DB_FILE = "test_sweeper.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@patch("app.sweeper.SessionLocal", TestingSessionLocal)
@patch("app.sweeper.queue")
def test_sweeper_repair(mock_queue):
    # 1. Prepare Database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # 2. Simulate a STRANDED task
    # Status = QUEUED, but updated_at is 60 seconds old
    stranded_time = datetime.utcnow() - timedelta(seconds=60)
    task_id = "stranded-task-999"
    stranded_task = Task(
        id=task_id,
        task_type="test_task",
        payload={},
        status=TaskStatus.QUEUED,
        updated_at=stranded_time
    )
    db.add(stranded_task)
    db.commit()
    
    print(f"Injected stranded task {task_id} with updated_at from {stranded_time}")

    # 3. Run Sweeper for one iteration
    with patch("time.sleep", side_effect=InterruptedError("Stop loop")):
        try:
            run_sweeper(interval=1, threshold_seconds=15)
        except InterruptedError:
            print("Sweeper iteration completed.")

    # 4. Verification
    # Verify Redis enqueue was called
    mock_queue.enqueue.assert_called_once_with(task_id)
    print("Verification passed: Stranded task repaired and enqueued.")

if __name__ == "__main__":
    test_sweeper_repair()
