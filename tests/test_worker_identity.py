import time
import os
import threading
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_identity.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("test_identity.db"):
    os.remove("test_identity.db")

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import Task, TaskStatus
from app.worker import process_task, WORKER_ID, HOSTNAME

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

def slow_task(payload):
    time.sleep(2)

@patch("app.worker.TASK_REGISTRY", {"slow": slow_task})
@patch("app.worker.queue")
def test_worker_attribution(mock_q):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # 1. Create task
    task_id = "identity-test"
    db.add(Task(id=task_id, task_type="slow", status=TaskStatus.QUEUED))
    db.commit()
    
    # 2. Run process_task in a thread to simulate worker activity
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    t = threading.Thread(target=process_task, args=(task_id, sem))
    t.start()
    
    # Give it a moment to claim
    time.sleep(0.5)
    
    # 3. Check status via API
    response = client.get(f"/tasks/{task_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    print(f"Task status: {data['status']}")
    print(f"Claimed by: {data['claimed_by']}")
    print(f"Worker host: {data['worker_host']}")
    
    assert data["status"] == "RUNNING"
    assert data["claimed_by"] == WORKER_ID
    assert data["worker_host"] == HOSTNAME
    
    t.join()
    print("Verification passed: Worker identity correctly attributed in DB.")

if __name__ == "__main__":
    test_worker_attribution()
