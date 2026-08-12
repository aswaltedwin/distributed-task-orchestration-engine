import redis
from app.config import settings
from typing import Optional, List
from app.models import TaskPriority

class TaskQueue:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        # Mapping priority to specific Redis list keys
        self.queues = {
            TaskPriority.HIGH: f"{settings.TASK_QUEUE}:high",
            TaskPriority.NORMAL: f"{settings.TASK_QUEUE}:normal",
            TaskPriority.LOW: f"{settings.TASK_QUEUE}:low"
        }
        self.processing_queue = settings.PROCESSING_QUEUE

    def enqueue(self, task_id: str, priority: TaskPriority = TaskPriority.NORMAL) -> None:
        """Pushes a task_id onto the specific priority queue."""
        queue_name = self.queues.get(priority, self.queues[TaskPriority.NORMAL])
        self.redis.lpush(queue_name, task_id)

    def reserve(self, timeout: int = 1) -> Optional[str]:
        """
        Atomically move task from highest available priority queue to processing.
        Uses a Lua script for multi-queue atomic RPOPLPUSH simulation.
        """
        # Lua script: Iterate through queues in order, RPOPLPUSH first non-empty to processing
        lua = """
        for i, queue in ipairs(KEYS) do
            local task = redis.call('RPOPLPUSH', queue, ARGV[1])
            if task then
                return task
            end
        end
        return nil
        """
        # We pass high, normal, low keys
        keys = [self.queues[TaskPriority.HIGH], self.queues[TaskPriority.NORMAL], self.queues[TaskPriority.LOW]]
        
        # Since RPOPLPUSH is non-blocking, we might need a small sleep if empty, 
        # but worker loop handles retries.
        return self.redis.eval(lua, 3, *keys, self.processing_queue)

    def ack(self, task_id: str) -> None:
        self.redis.lrem(self.processing_queue, 0, task_id)

    def requeue(self, task_id: str, priority: TaskPriority = TaskPriority.NORMAL) -> None:
        """Move from processing back to its priority queue."""
        queue_name = self.queues.get(priority, self.queues[TaskPriority.NORMAL])
        lua = """
        local removed = redis.call('LREM', KEYS[1], 0, ARGV[1])
        if removed > 0 then
            redis.call('LPUSH', KEYS[2], ARGV[1])
            return 1
        end
        return 0
        """
        self.redis.eval(lua, 2, self.processing_queue, queue_name, task_id)

# Global instance
queue = TaskQueue()
