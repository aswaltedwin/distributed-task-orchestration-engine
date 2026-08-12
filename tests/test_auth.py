import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_auth.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("test_auth.db"):
    os.remove("test_auth.db")

from app.main import app
from app.database import Base, engine

client = TestClient(app)

def test_auth_protected_routes():
    # Prepare DB
    Base.metadata.create_all(bind=engine)
    
    # 1. Test POST /tasks without key
    response = client.post("/tasks", json={"task_type": "test", "payload": {}})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API Key"
    
    # 2. Test POST /tasks with wrong key
    response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    
    # 3. Test POST /tasks with correct key
    # Mock Redis to avoid connection errors
    with patch("app.main.queue") as mock_queue:
        response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "supersecret"})
        assert response.status_code == 200
        assert response.json()["status"] == "QUEUED"

    # 4. Test GET /metrics without key
    response = client.get("/metrics")
    assert response.status_code == 401

    # 5. Test GET /metrics with correct key
    response = client.get("/metrics", headers={"X-API-Key": "supersecret"})
    assert response.status_code == 200

    # 6. Test GET /tasks/{id} (Public route)
    # We need a task ID first
    task_id = "test-task-id"
    response = client.get(f"/tasks/{task_id}")
    # Should be 404 but NOT 401
    assert response.status_code == 404

    print("Verification passed: Auth correctly applied to routes.")

if __name__ == "__main__":
    test_auth_protected_routes()
