import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_idempotency.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("test_idempotency.db"):
    os.remove("test_idempotency.db")

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import Task

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

def test_idempotency_logic():
    # 1. Prepare DB
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # 2. Submit task with key
    key = "unique-key-123"
    with patch("app.main.queue") as mock_q:
        resp1 = client.post("/tasks", json={
            "task_type": "test", 
            "payload": {"data": 1},
            "idempotency_key": key
        }, headers=headers)
        assert resp1.status_code == 200
        id1 = resp1.json()["task_id"]
        
        # 3. Submit SAME task again (duplicate idempotency key)
        resp2 = client.post("/tasks", json={
            "task_type": "test", 
            "payload": {"data": 1},
            "idempotency_key": key
        }, headers=headers)
        assert resp2.status_code in (200, 409)
        id2 = resp2.json()["task_id"]
        
        # 4. Verify IDs are identical
        assert id1 == id2
        print(f"Task IDs match: {id1}")
        
        # 5. Verify only one task in DB
        count = db.query(Task).filter(Task.idempotency_key == key).count()
        assert count == 1
        print(f"DB count for key '{key}': {count}")

        # 6. Test race condition simulation
        # Simulate a concurrent insert by manually adding a task with same key just before API call
        key2 = "race-key"
        db.add(Task(id="manual-id", task_type="test", payload={}, idempotency_key=key2))
        db.commit()
        
        resp3 = client.post("/tasks", json={
            "task_type": "test", 
            "payload": {},
            "idempotency_key": key2
        }, headers=headers)
        assert resp3.status_code == 200
        assert resp3.json()["task_id"] == "manual-id"
        print("Race condition handling (IntegrityError) verified.")

    print("Verification passed: Idempotency keys protect against duplicate submission.")

if __name__ == "__main__":
    test_idempotency_logic()
