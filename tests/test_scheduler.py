import time
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.scheduler import run_scheduler

# Setup file-based SQLite for testing
DB_FILE = "test_scheduler.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@patch("app.scheduler.SessionLocal", TestingSessionLocal)
@patch("app.scheduler.queue")
def test_scheduler_promotion(mock_queue):
    # 1. Prepare Database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # 2. Create a SCHEDULED task for 5 seconds in the future
    due_time = datetime.now() + timedelta(seconds=5)
    task_id = "scheduled-task-123"
    scheduled_task = Task(
        id=task_id,
        task_type="test_task",
        payload={},
        status=TaskStatus.SCHEDULED,
        run_at=due_time
    )
    db.add(scheduled_task)
    db.commit()
    
    print(f"Created scheduled task {task_id} for {due_time}")

    # 3. Run Scheduler multiple times
    # We'll simulate 8 seconds of scheduler ticks
    for i in range(10):
        print(f"Tick {i} (time: {datetime.now()})")
        # Run one iteration of the scheduler logic by patching its internal sleep
        with patch("app.scheduler.time.sleep", side_effect=InterruptedError("Stop")):
            try:
                run_scheduler(interval=1)
            except InterruptedError:
                pass
        
        db.refresh(scheduled_task)
        if scheduled_task.status == TaskStatus.QUEUED:
            print(f"Task promoted at tick {i}")
            break
        time.sleep(1)

    # 4. Verification
    db.refresh(scheduled_task)
    print(f"Final Task Status: {scheduled_task.status}")

    assert scheduled_task.status == TaskStatus.QUEUED
    mock_queue.enqueue.assert_called_once_with(task_id, priority=scheduled_task.priority)
    print("Verification passed: Task promoted and enqueued correctly.")

if __name__ == "__main__":
    test_scheduler_promotion()
