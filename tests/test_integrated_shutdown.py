import time
import os
import threading
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 1. Environment Setup
os.environ["DATABASE_URL"] = "sqlite:///test_shutdown.db"
os.environ["API_KEY"] = "supersecret"

try:
    if os.path.exists("test_shutdown.db"):
        os.remove(os.path.exists("test_shutdown.db") and "test_shutdown.db" or "")
except Exception:
    pass

from app.database import Base, engine, SessionLocal
from app.main import app
from app.models import Task, TaskStatus
from app.worker import run_worker, shutdown_event

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

@patch("app.worker.queue")
def test_graceful_shutdown(mock_queue):
    Base.metadata.create_all(bind=engine)
    
    # 1. Submit tasks
    task_ids = []
    for i in range(3):
        # We need to manually simulate the Redis queue for the worker to pick them up
        task_id = f"shutdown-task-{i}"
        task_ids.append(task_id)
        with SessionLocal() as db:
            db.add(Task(id=task_id, task_type="send_email", payload={}, status=TaskStatus.QUEUED))
            db.commit()
            
    # Mock reserve to return these tasks then None
    mock_queue.reserve.side_effect = task_ids + [None] * 100
    
    # 2. Start worker in background
    print("--- STARTING WORKER FOR SHUTDOWN TEST ---")
    worker_thread = threading.Thread(target=run_worker)
    worker_thread.start()
    
    time.sleep(1) # Allow some tasks to start
    
    # 3. Trigger Shutdown
    print("--- TRIGGERING SHUTDOWN ---")
    shutdown_event.set()
    
    # 4. Wait for worker to exit
    start_wait = time.time()
    worker_thread.join(timeout=10)
    wait_duration = time.time() - start_wait
    
    print(f"Worker exited in {wait_duration:.2f}s")
    
    # 5. Verification
    with SessionLocal() as db:
        success_count = db.query(Task).filter(Task.status == TaskStatus.SUCCESS).count()
        print(f"Tasks completed: {success_count}/{len(task_ids)}")
        
    assert not worker_thread.is_alive()
    assert success_count == len(task_ids)
    print("GRACEFUL SHUTDOWN: PASS")

if __name__ == "__main__":
    test_graceful_shutdown()
