import time
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, and_, func
from app.database import SessionLocal
from app.models import Task, TaskStatus
from app.queue import queue
from app.config import settings

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("reaper")

def run_reaper(interval: int = 5, threshold_seconds: int = 7):
    logger.info(f"Reaper started. Interval: {interval}s, Threshold: {threshold_seconds}s")
    
    while True:
        try:
            with SessionLocal() as db:
                # 1. Define Staleness Threshold
                threshold = datetime.utcnow() - timedelta(seconds=threshold_seconds)
                
                # 2. Query for stale RUNNING tasks with locking
                # FOR UPDATE SKIP LOCKED prevents multiple reapers from colliding
                stmt = (
                    select(Task)
                    .where(
                        and_(
                            Task.status == TaskStatus.RUNNING,
                            Task.heartbeat_at < threshold
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                
                stale_tasks = db.execute(stmt).scalars().all()
                
                for task in stale_tasks:
                    logger.warning(f"Detected stale task: {task.id} (Last heartbeat: {task.heartbeat_at})")
                    
                    if task.retry_count < settings.MAX_RETRIES:
                        # 3. Retry transition
                        logger.info(f"Requeuing task {task.id} (Retry {task.retry_count + 1}/{settings.MAX_RETRIES})")
                        task.retry_count += 1
                        task.status = TaskStatus.QUEUED
                        task.heartbeat_at = None
                        task.last_error = "Recovered stale task after heartbeat timeout"
                        db.commit()
                        
                        try:
                            queue.enqueue(task.id, priority=task.priority)
                        except Exception as e:
                            # DB is already QUEUED, sweeper will pick it up if Redis fails
                            logger.error(f"Failed to requeue task {task.id} to Redis: {e}")
                    else:
                        # 4. Dead letter transition
                        logger.error(f"Task {task.id} exhausted retries after crash. Moving to DEAD_LETTER.")
                        task.status = TaskStatus.DEAD_LETTER
                        task.heartbeat_at = None
                        db.commit()

        except Exception as e:
            logger.error(f"Reaper loop error: {e}")
        
        time.sleep(interval)

if __name__ == "__main__":
    run_reaper()
