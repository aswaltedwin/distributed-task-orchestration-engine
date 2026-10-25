import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_admin.db"
os.environ["API_KEY"] = "supersecret"

try:
    if os.path.exists("test_admin.db"):
        os.remove("test_admin.db")
except Exception:
    pass

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import Task, TaskStatus

client = TestClient(app)

@patch("app.main.queue")
def test_admin_dashboard(mock_q):
    # Setup mocks
    mock_q.redis.ping.return_value = True
    mock_q.redis.incr.return_value = 1
    
    # 1. Prepare DB
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    
    # 2. Seed data
    # 2 Queued, 1 Running, 1 Dead Letter, 1 Scheduled
    db.add(Task(id="t1", task_type="t", status=TaskStatus.QUEUED))
    db.add(Task(id="t2", task_type="t", status=TaskStatus.QUEUED))
    db.add(Task(id="t3", task_type="t", status=TaskStatus.RUNNING))
    db.add(Task(id="t4", task_type="t", status=TaskStatus.DEAD_LETTER, last_error="Crash"))
    db.add(Task(id="t5", task_type="t", status=TaskStatus.SCHEDULED, run_at=datetime.now() + timedelta(hours=1)))
    db.commit()
    
    headers = {"X-API-Key": "supersecret"}
    
    # 3. Test /admin/health
    response = client.get("/admin/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["checks"]["redis"] == "ok"
    assert response.json()["worker_capacity"] == 3

    # 4. Test /admin/stats
    response = client.get("/admin/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["queued"] == 2
    assert data["running"] == 1
    assert data["dead_letter"] == 1
    assert data["scheduled"] == 1

    # 5. Test /admin/dead-letter
    response = client.get("/admin/dead-letter", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "t4"
    assert data[0]["last_error"] == "Crash"

    # 6. Test /admin/scheduled
    response = client.get("/admin/scheduled", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "t5"

    # 6a. Test /admin/tasks (Task list and filters)
    response = client.get("/admin/tasks", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 5
    # Filter by status
    response = client.get("/admin/tasks?status=RUNNING", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == "t3"

    # 6b. Test /admin/tasks/{task_id}/requeue
    mock_q.enqueue.reset_mock()
    response = client.post("/admin/tasks/t4/requeue", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "requeued"
    mock_q.enqueue.assert_called_once_with("t4", priority=db.get(Task, "t4").priority)
    
    # Verify db reset
    t4 = db.get(Task, "t4")
    assert t4.status == TaskStatus.QUEUED
    assert t4.retry_count == 0
    assert t4.last_error is None

    # 6c. Test /dashboard response
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Antigravity Control" in response.text

    # 7. Test Auth protection
    response = client.get("/admin/stats")
    assert response.status_code == 401

    db.close()
    print("Verification passed: Admin endpoints return accurate system state.")

if __name__ == "__main__":
    test_admin_dashboard()
