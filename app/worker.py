import time
import logging
import threading
import signal
import os
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import update, func
from app.queue import queue
from app.database import SessionLocal
from datetime import datetime, timedelta
from app.models import Task, TaskStatus
from app.tasks import TASK_REGISTRY
from app.config import settings
from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("worker")

# Worker Identity
WORKER_ID = str(uuid.uuid4())[:8]
HOSTNAME = socket.gethostname()

# Global shutdown event
shutdown_event = threading.Event()

def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}. Initiating graceful shutdown...", extra={"worker_id": WORKER_ID, "event": "shutdown_signal"})
    shutdown_event.set()

# Register signals
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def heartbeat_loop(task_id: str, stop_event: threading.Event, interval: int = 5):
    """Periodically updates heartbeat_at for a running task."""
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                stmt = (
                    update(Task)
                    .where(Task.id == task_id)
                    .values(heartbeat_at=func.now())
                )
                db.execute(stmt)
                db.commit()
        except Exception as e:
            logger.error(f"Heartbeat failed", extra={"task_id": task_id, "worker_id": WORKER_ID, "error": str(e)})
        
        if stop_event.wait(timeout=interval):
            break

from app.metrics import (
    TASKS_ACTIVE, 
    TASKS_SUCCESS, 
    TASKS_FAILED, 
    TASKS_RETRIED, 
    TASK_EXECUTION_DURATION
)

import multiprocessing

def task_wrapper(task_type: str, payload: dict, result_queue: multiprocessing.Queue):
    """Entry point for the subprocess. Isolated from the parent GIL and session."""
    try:
        handler = TASK_REGISTRY.get(task_type)
        if not handler:
            result_queue.put({"success": False, "error": f"Unknown task type: {task_type}"})
            return
        
        handler(payload)
        result_queue.put({"success": True})
    except Exception as e:
        result_queue.put({"success": False, "error": f"{type(e).__name__}: {str(e)}"})

def process_task(task_id: str, semaphore: threading.BoundedSemaphore):
    """Task executor thread. Manages a subprocess for the actual execution."""
    start_time = time.time()
    try:
        with SessionLocal() as db:
            try:
                # 1. Atomic DB Claim with attribution
                stmt = (
                    update(Task)
                    .where(Task.id == task_id)
                    .where(Task.status == TaskStatus.QUEUED)
                    .values(
                        status=TaskStatus.RUNNING, 
                        heartbeat_at=func.now(),
                        claimed_by=WORKER_ID,
                        worker_host=HOSTNAME
                    )
                )
                result = db.execute(stmt)
                db.commit()

                if result.rowcount == 0:
                    logger.warning(f"Claim failed", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "claim_failed"})
                    queue.ack(task_id)
                    return

                TASKS_ACTIVE.inc()
                task = db.query(Task).filter(Task.id == task_id).first()
                
                # 2. Heartbeat setup (Parent thread owns this)
                stop_heartbeat = threading.Event()
                heartbeat_thread = threading.Thread(
                    target=heartbeat_loop,
                    args=(task_id, stop_heartbeat),
                    daemon=True
                )
                heartbeat_thread.start()

                try:
                    # 3. Check for early cancellation
                    if task.cancel_requested:
                        logger.info(f"Cancelled pre-exec", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "cancelled_pre_exec"})
                        task.status = TaskStatus.CANCELLED
                        db.commit()
                        queue.ack(task_id)
                        return

                    # 4. Execution via Subprocess (Hard Timeout Enforcement)
                    result_queue = multiprocessing.Queue()
                    process = multiprocessing.Process(
                        target=task_wrapper,
                        args=(task.task_type, task.payload, result_queue)
                    )
                    
                    process.start()
                    # Wait for completion or timeout
                    process.join(timeout=task.timeout)

                    if process.is_alive():
                        # TIMEOUT REACHED
                        logger.error(f"Task timed out after {task.timeout}s - Killing process", 
                                     extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "timeout"})
                        process.kill()
                        process.join() # Clean up zombie
                        raise TimeoutError(f"Task execution exceeded hard limit of {task.timeout} seconds")

                    # Check result from queue
                    if not result_queue.empty():
                        res = result_queue.get()
                        if not res["success"]:
                            raise Exception(res["error"])
                    else:
                        # Process died without putting anything in queue (e.g. segfault)
                        if process.exitcode != 0:
                            raise Exception(f"Task process exited unexpectedly with code {process.exitcode}")

                    # Refresh to check for cancellation during execution
                    db.refresh(task)
                    if task.cancel_requested:
                        logger.info(f"Cancelled post-exec", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "cancelled_post_exec"})
                        task.status = TaskStatus.CANCELLED
                        db.commit()
                        queue.ack(task_id)
                        return

                    # 5. Success handling
                    task.status = TaskStatus.SUCCESS
                    task.last_error = None
                    db.commit()
                    queue.ack(task_id)
                    TASKS_SUCCESS.inc()
                    logger.info(f"Task succeeded", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "success"})

                except Exception as e:
                    # 6. Failure handling
                    TASKS_FAILED.inc()
                    logger.error(f"Task failed: {e}", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "failure", "retry_count": task.retry_count + 1})
                    task.status = TaskStatus.FAILED
                    task.retry_count += 1
                    task.last_error = f"{type(e).__name__}: {str(e)}"
                    db.commit()

                    if task.retry_count <= settings.MAX_RETRIES:
                        base_backoff = 5 
                        wait_seconds = base_backoff * (2 ** (task.retry_count - 1))
                        import random
                        jitter = wait_seconds * 0.2 * (random.random() * 2 - 1)
                        wait_seconds = max(1, wait_seconds + jitter)
                        
                        task.run_at = datetime.utcnow() + timedelta(seconds=wait_seconds)
                        task.status = TaskStatus.SCHEDULED
                        
                        logger.info(f"Retrying task", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "retry_scheduled", "retry_count": task.retry_count, "wait_sec": round(wait_seconds, 1)})
                        TASKS_RETRIED.inc()
                        db.commit()
                        queue.ack(task_id)
                    else:
                        logger.warning(f"Task exhausted", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "exhausted"})
                        task.status = TaskStatus.DEAD_LETTER
                        db.commit()
                        queue.ack(task_id)
                finally:
                    stop_heartbeat.set()
                    heartbeat_thread.join(timeout=1)
                    TASK_EXECUTION_DURATION.observe(time.time() - start_time)
                    TASKS_ACTIVE.dec()

            except Exception as e:
                logger.error(f"Internal executor error", extra={"task_id": task_id, "worker_id": WORKER_ID, "error": str(e)})
    finally:
        semaphore.release()

def run_worker():
    concurrency = settings.WORKER_CONCURRENCY
    logger.info(f"Worker instance {WORKER_ID} started on {HOSTNAME}", extra={"worker_id": WORKER_ID, "host": HOSTNAME, "concurrency": concurrency, "event": "startup"})
    
    semaphore = threading.BoundedSemaphore(concurrency)
    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=f"Worker-{WORKER_ID}")

    while not shutdown_event.is_set():
        try:
            if not semaphore.acquire(timeout=1):
                continue
            
            task_id = queue.reserve(timeout=1)
            if not task_id:
                semaphore.release()
                continue

            logger.info(f"Dispatching task {task_id}", extra={"task_id": task_id, "worker_id": WORKER_ID, "event": "dispatch"})
            executor.submit(process_task, task_id, semaphore)
            
        except Exception as e:
            logger.error(f"Dispatcher error", extra={"worker_id": WORKER_ID, "error": str(e)})
            if not shutdown_event.is_set():
                time.sleep(1)

    logger.info("Draining active tasks...", extra={"worker_id": WORKER_ID, "event": "draining"})
    executor.shutdown(wait=True, cancel_futures=True)
    logger.info("Worker shutdown complete.", extra={"worker_id": WORKER_ID, "event": "shutdown_complete"})

if __name__ == "__main__":
    run_worker()
