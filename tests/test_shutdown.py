import time
import os
import threading
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, TaskStatus
from app.worker import run_worker, shutdown_event

# Setup file-based SQLite
DB_FILE = "test_shutdown_v2.db"
try:
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
except Exception:
    pass

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def slow_handler(payload):
    print(f"Task starting 5s work...")
    time.sleep(5)
    print(f"Task finished.")

@patch("app.worker.SessionLocal", TestingSessionLocal)
@patch("app.worker.queue")
def test_graceful_shutdown(mock_queue):
    # 1. Prepare DB
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    db.add(Task(id="shutdown-task-1", task_type="generate_report", payload={}, status=TaskStatus.QUEUED))
    db.commit()

    # 2. Mock Redis
    # First call returns task, subsequent calls return None
    mock_queue.reserve.side_effect = ["shutdown-task-1"] + [None] * 100

    # 3. Start Worker in a Thread
    print("\nStarting worker thread...")
    worker_thread = threading.Thread(target=run_worker)
    worker_thread.start()

    # 4. Wait for task pickup
    time.sleep(2)
    
    # 5. Trigger Shutdown
    print("Triggering shutdown_event...")
    shutdown_event.set()
    start_shutdown = time.time()

    # 6. Wait for worker to finish
    worker_thread.join(timeout=15)
    
    end_shutdown = time.time()
    print(f"Worker exited after {end_shutdown - start_shutdown:.2f} seconds.")

    # 7. Verification
    db = TestingSessionLocal()
    task = db.query(Task).filter(Task.id == "shutdown-task-1").first()
    print(f"Final Task Status: {task.status}")

    assert task.status == TaskStatus.SUCCESS
    print("Verification passed: Task finished gracefully after shutdown signal.")

if __name__ == "__main__":
    test_graceful_shutdown()
