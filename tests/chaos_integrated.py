import time
import threading
import os
import fakeredis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.models import Task, TaskStatus, TaskPriority
import app.worker
import app.reaper
import app.scheduler
import app.queue
import app.main
from fastapi.testclient import TestClient
from unittest.mock import patch

# Global Config
DB_PATH = "chaos_integrated.db"
shared_redis = fakeredis.FakeStrictRedis(decode_responses=True)

def setup_infra():
    if os.path.exists(DB_PATH):
        try: os.remove(DB_PATH)
        except: pass

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try: yield db
        finally: db.close()

    app.main.app.dependency_overrides[get_db] = override_get_db
    app.worker.SessionLocal = TestingSessionLocal
    app.reaper.SessionLocal = TestingSessionLocal
    app.scheduler.SessionLocal = TestingSessionLocal

    app.worker.queue.redis = shared_redis
    app.reaper.queue.redis = shared_redis
    app.scheduler.queue.redis = shared_redis
    app.main.queue.redis = shared_redis
    
    return TestingSessionLocal

class ChaosWorker:
    def __init__(self, name):
        self.name = name
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        def run():
            with patch("app.worker.shutdown_event", self.stop_event):
                app.worker.run_worker()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def kill(self):
        print(f"KILLING Worker {self.name}!")
        self.stop_event.set()

def test_distributed_chaos(SessionLocal):
    print("--- Starting Integrated Chaos Validation ---")
    
    # 1. Start Background Components
    threading.Thread(target=app.reaper.run_reaper, args=(2, 3), daemon=True).start()
    threading.Thread(target=app.scheduler.run_scheduler, args=(1,), daemon=True).start()
    
    w1 = ChaosWorker("W1")
    w2 = ChaosWorker("W2")
    w1.start()
    w2.start()
    
    time.sleep(2)
    client = TestClient(app.main.app)
    headers = {"X-API-Key": "supersecret"}
    
    # 2. Test A: Worker Crash Recovery
    print("\n[Test A] Worker Crash & Reaper Recovery")
    resp = client.post("/tasks", json={
        "task_type": "chaos_sleep", "payload": {"id": "chaos-1"}
    }, headers=headers)
    tid = resp.json()["task_id"]
    
    time.sleep(2)
    db = SessionLocal()
    task = db.get(Task, tid)
    owner1 = task.claimed_by
    print(f"Task {tid} claimed by Worker: {owner1}")
    
    w1.kill()
    w2.kill()
    
    print("Waiting for Reaper (10s)...")
    time.sleep(10)
    
    db.expire_all()
    task = db.get(Task, tid)
    print(f"Task {tid} Status: {task.status}, Retry Count: {task.retry_count}")
    assert task.status == TaskStatus.QUEUED or task.retry_count > 0
    print("SUCCESS: Reaper recovered task from dead worker.")

    # 3. Test B: Priority Preemption
    print("\n[Test B] Global Priority Preemption")
    w3 = ChaosWorker("W3")
    w3.start() # Start one worker to process
    
    for i in range(5):
        client.post("/tasks", json={
            "task_type": "chaos_sleep", "payload": {"p": i}, "priority": "LOW"
        }, headers=headers)
    
    time.sleep(1)
    resp = client.post("/tasks", json={
        "task_type": "echo", "payload": {"p": "win"}, "priority": "HIGH"
    }, headers=headers)
    high_tid = resp.json()["task_id"]
    
    time.sleep(5)
    db.expire_all()
    high_task = db.get(Task, high_tid)
    print(f"HIGH Task Status: {high_task.status}")
    assert high_task.status in [TaskStatus.RUNNING, TaskStatus.SUCCESS]
    print("SUCCESS: High priority task prioritized over LOW backlog.")

    print("\n--- Integrated Chaos Validation Complete: PASS ---")

if __name__ == "__main__":
    # REQUIRED for Windows multiprocessing
    SessionLocal = setup_infra()
    test_distributed_chaos(SessionLocal)
