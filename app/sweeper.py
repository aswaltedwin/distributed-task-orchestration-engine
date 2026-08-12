import time
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from app.database import SessionLocal
from app.models import Task, TaskStatus
from app.queue import queue

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("sweeper")

def run_sweeper(interval: int = 30, threshold_seconds: int = 30, batch_size: int = 50):
    logger.info(f"Sweeper started. Threshold: {threshold_seconds}s, Batch Size: {batch_size}")
    
    while True:
        try:
            with SessionLocal() as db:
                # 1. Define Staleness Threshold for QUEUED tasks
                # Using updated_at (Choice B) to catch reaped tasks that failed to enqueue
                threshold = datetime.utcnow() - timedelta(seconds=threshold_seconds)
                
                # 2. Find stranded QUEUED tasks
                stmt = (
                    select(Task)
                    .where(
                        and_(
                            Task.status == TaskStatus.QUEUED,
                            Task.updated_at < threshold
                        )
                    )
                    .limit(batch_size)
                )
                
                stranded_tasks = db.execute(stmt).scalars().all()
                
                if stranded_tasks:
                    logger.info(f"Found {len(stranded_tasks)} stranded tasks. Attempting repair.")
                
                for task in stranded_tasks:
                    try:
                        # 3. Attempt Redis Enqueue
                        # No DB update needed yet; atomic claim handles the rest
                        queue.enqueue(task.id, priority=task.priority)
                        logger.info(f"Successfully repaired task {task.id}")
                    except Exception as e:
                        logger.error(f"Failed to repair task {task.id}: {e}")

        except Exception as e:
            logger.error(f"Sweeper loop error: {e}")
        
        time.sleep(interval)

if __name__ == "__main__":
    run_sweeper()
