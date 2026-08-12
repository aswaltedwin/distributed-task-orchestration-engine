import time
import logging
from datetime import datetime
from sqlalchemy import update, select, and_
from app.database import SessionLocal
from app.models import Task, TaskStatus
from app.queue import queue

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("scheduler")

def run_scheduler(interval: int = 5):
    logger.info(f"Scheduler started. Interval: {interval}s")
    
    while True:
        try:
            with SessionLocal() as db:
                # 1. Atomic Promotion: SCHEDULED -> QUEUED for tasks due
                # We do this one by one or in batches, but the update itself must be atomic
                # and we need to know WHICH tasks were promoted to enqueue them in Redis.
                
                now = datetime.now()
                
                # We'll find IDs first, then update them atomically to avoid race conditions 
                # if multiple schedulers are running.
                
                # Better: Use a subquery or a returning clause if supported, 
                # but for SQLite/Postgres compatibility we'll use a locked select or a multi-step atomic update.
                
                # Optimized approach for MVP:
                # 1. Update status to QUEUED where status=SCHEDULED and run_at <= now
                # 2. But we need the IDs. So we'll use a more complex query.
                
                # Simple and safe for multiple schedulers:
                stmt = (
                    select(Task)
                    .where(
                        and_(
                            Task.status == TaskStatus.SCHEDULED,
                            Task.run_at <= now
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                
                tasks = db.execute(stmt).scalars().all()
                
                for task in tasks:
                    # Atomic status transition
                    task.status = TaskStatus.QUEUED
                    db.commit()
                    
                    logger.info(f"Promoted task {task.id} to QUEUED (Priority: {task.priority})")
                    try:
                        queue.enqueue(task.id, priority=task.priority)
                    except Exception as e:
                        logger.error(f"Failed to enqueue promoted task {task.id}: {e}")

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
        
        time.sleep(interval)

if __name__ == "__main__":
    run_scheduler()
