import os
import fakeredis
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set env before imports
os.environ["DATABASE_URL"] = "sqlite:///test_priority.db"
os.environ["API_KEY"] = "supersecret"

if os.path.exists("test_priority.db"):
    os.remove(os.path.exists("test_priority.db") and "test_priority.db" or "")

from app.models import Base, TaskPriority
from app.queue import TaskQueue

def test_priority_drain():
    # 1. Initialize TaskQueue with fakeredis
    queue = TaskQueue()
    queue.redis = fakeredis.FakeStrictRedis(decode_responses=True)
    
    # 2. Clear queues
    for q_name in queue.queues.values():
        queue.redis.delete(q_name)
    queue.redis.delete(queue.processing_queue)
    
    # 3. Seed tasks: 3 LOW, then 1 HIGH
    # Enqueue LOW tasks
    for i in range(3):
        queue.enqueue(f"low-{i}", priority=TaskPriority.LOW)
    
    # Enqueue HIGH task
    queue.enqueue("high-0", priority=TaskPriority.HIGH)
    
    # 4. Verify priority drain
    # HIGH should come out first even though it was pushed last
    first_pick = queue.reserve()
    print(f"First task picked: {first_pick}")
    assert first_pick == "high-0"
    
    # Ensure it moved to processing
    assert queue.redis.lindex(queue.processing_queue, 0) == "high-0"
    
    # Next should be LOW-0
    second_pick = queue.reserve()
    print(f"Second task picked: {second_pick}")
    assert second_pick == "low-0"
    
    # Next LOW-1
    third_pick = queue.reserve()
    print(f"Third task picked: {third_pick}")
    assert third_pick == "low-1"

    print("Verification passed: Multi-queue Lua script correctly respects priority order.")

if __name__ == "__main__":
    test_priority_drain()
