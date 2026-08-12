import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_ratelimit.db"
os.environ["API_KEY"] = "supersecret"
os.environ["RATE_LIMIT_PER_MINUTE"] = "3"

try:
    if os.path.exists("test_ratelimit.db"):
        os.remove(os.path.exists("test_ratelimit.db") and "test_ratelimit.db" or "")
except Exception:
    pass

from app.main import app
from app.database import Base, engine
from app.config import settings

client = TestClient(app)

def test_rate_limiting():
    # Prepare DB
    Base.metadata.create_all(bind=engine)
    settings.RATE_LIMIT_PER_MINUTE = 3
    
    # Mock Redis INCR to simulate counts
    with patch("app.main.queue") as mock_queue:
        # Mocking redis.incr side effect: 1, 2, 3, 4
        mock_queue.redis.incr.side_effect = [1, 2, 3, 4]
        
        # 1st request (count 1)
        response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "supersecret"})
        assert response.status_code == 200
        
        # 2nd request (count 2)
        response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "supersecret"})
        assert response.status_code == 200
        
        # 3rd request (count 3)
        response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "supersecret"})
        assert response.status_code == 200
        
        # 4th request (count 4) - Should trigger 429
        response = client.post("/tasks", json={"task_type": "test", "payload": {}}, headers={"X-API-Key": "supersecret"})
        assert response.status_code == 429
        assert response.json()["detail"] == "Rate limit exceeded"
        
        print("Verification passed: Rate limiting triggered 429 correctly after 3 requests.")

if __name__ == "__main__":
    test_rate_limiting()
