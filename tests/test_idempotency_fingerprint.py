import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_idempotency_fp.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("test_idempotency_fp.db"):
    os.remove("test_idempotency_fp.db")

from app.main import app
from app.database import Base, engine

client = TestClient(app)
headers = {"X-API-Key": "supersecret"}

@patch("app.main.queue")
def test_fingerprint_validation(mock_q):
    Base.metadata.create_all(bind=engine)
    
    key = "fixed-key"
    
    # 1. First submission
    resp1 = client.post("/tasks", json={
        "task_type": "email",
        "payload": {"to": "a@test.com"},
        "idempotency_key": key
    }, headers=headers)
    assert resp1.status_code == 200
    
    # 2. Same key, different type
    resp2 = client.post("/tasks", json={
        "task_type": "delete_user",
        "payload": {"to": "a@test.com"},
        "idempotency_key": key
    }, headers=headers)
    assert resp2.status_code == 409
    assert "Idempotency key conflict" in resp2.json()["detail"]
    print("Conflict detected for different task_type: PASS")
    
    # 3. Same key, different payload
    resp3 = client.post("/tasks", json={
        "task_type": "email",
        "payload": {"to": "b@test.com"},
        "idempotency_key": key
    }, headers=headers)
    assert resp3.status_code == 409
    print("Conflict detected for different payload: PASS")
    
    # 4. Same key, same everything
    resp4 = client.post("/tasks", json={
        "task_type": "email",
        "payload": {"to": "a@test.com"},
        "idempotency_key": key
    }, headers=headers)
    assert resp4.status_code == 200
    assert resp4.json()["task_id"] == resp1.json()["task_id"]
    print("Deduplication successful for matching fingerprint: PASS")

if __name__ == "__main__":
    test_fingerprint_validation()
