import os
import time
import threading
from unittest.mock import MagicMock, patch

# CRITICAL: Set DATABASE_URL and API_KEY before importing app modules
SQLALCHEMY_DATABASE_URL = 'sqlite:///test_metrics_v4.db'
os.environ['DATABASE_URL'] = SQLALCHEMY_DATABASE_URL
os.environ['API_KEY'] = 'supersecret'

try:
    if os.path.exists('test_metrics_v4.db'):
        os.remove('test_metrics_v4.db')
except Exception:
    pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Mock Redis BEFORE importing app.main
with patch('app.queue.queue') as mock_q:
    from app.database import Base, engine
    from app.main import app
    from app.models import Task, TaskStatus
    from app.worker import process_task

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)
headers = {'X-API-Key': 'supersecret'}

@patch('app.main.queue')
@patch('app.worker.SessionLocal', TestingSessionLocal)
@patch('app.worker.queue')
def test_metrics_flow(mock_worker_queue, mock_main_queue):
    # 1. Prepare DB
    Base.metadata.create_all(bind=engine)
    
    # 2. Submit 2 tasks via API
    r1 = client.post('/tasks', json={'task_type': 'echo', 'payload': {}}, headers=headers)
    r2 = client.post('/tasks', json={'task_type': 'fail', 'payload': {}}, headers=headers)
    t1_id = r1.json()['task_id']
    t2_id = r2.json()['task_id']
    
    # 3. Manually run worker logic on only these 2 tasks
    semaphore = threading.BoundedSemaphore(10)
    for tid in [t1_id, t2_id]:
        semaphore.acquire()
        process_task(tid, semaphore)
    
    # 4. Check /metrics
    response = client.get('/metrics', headers=headers)
    print('\n--- Metrics Output ---')
    print(response.text)
    print('----------------------')
    
    assert response.status_code == 200
    assert 'tasks_submitted_total 2.0' in response.text
    assert 'tasks_success_total 1.0' in response.text
    assert 'tasks_failed_total 1.0' in response.text
    
    print('Verification passed: All metrics tracked correctly.')

if __name__ == '__main__':
    test_metrics_flow()
