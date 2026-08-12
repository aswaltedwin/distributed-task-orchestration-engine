from fastapi import FastAPI, Depends, HTTPException, Response, Security
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
import os
from app.schemas import TaskCreateRequest, TaskResponse
from app.database import engine, Base, get_db
from app.models import Task, TaskStatus
from app.queue import queue
from app.metrics import TASKS_SUBMITTED, TASKS_CANCELLED, get_metrics_report
from app.config import settings
import logging
from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("api")

# Auth dependency
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    
    # Rate Limiting Logic (Fixed Window)
    minute_key = datetime.now().strftime("%Y-%m-%d-%H-%M")
    redis_key = f"ratelimit:{api_key}:{minute_key}"
    
    try:
        # Increment and set TTL if new
        count = queue.redis.incr(redis_key)
        if count == 1:
            queue.redis.expire(redis_key, 60)
        
        if count > settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    except HTTPException:
        raise
    except Exception as e:
        # Fallback: if Redis is down, allow request but log error
        # In a strict production system, you might block.
        logger.error(f"Rate limiter error: {e}", extra={"event": "ratelimit_error"})
        
    return api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API started", extra={"event": "startup"})
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/metrics")
def metrics(api_key: str = Depends(get_api_key)):
    data, content_type = get_metrics_report()
    return Response(content=data, media_type=content_type)

@app.post("/tasks", response_model=TaskResponse)
def create_task(request: TaskCreateRequest, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    # 0. Check Idempotency
    if request.idempotency_key:
        existing = db.query(Task).filter(Task.idempotency_key == request.idempotency_key).first()
        if existing:
            # Fingerprint validation: Do the intents match?
            if existing.task_type != request.task_type or existing.payload != request.payload:
                raise HTTPException(
                    status_code=409, 
                    detail="Idempotency key conflict: existing task has different type or payload"
                )
            return TaskResponse(task_id=existing.id, status=existing.status)

    # 1. Determine initial status and run_at logic
    now = datetime.now()
    status = TaskStatus.QUEUED
    is_immediate = True

    if request.run_at and request.run_at > now:
        status = TaskStatus.SCHEDULED
        is_immediate = False

    # 2. Persist task to database
    new_task = Task(
        task_type=request.task_type,
        payload=request.payload,
        status=status,
        run_at=request.run_at,
        idempotency_key=request.idempotency_key,
        priority=request.priority,
        timeout=request.timeout
    )
    
    try:
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
    except Exception: # Likely IntegrityError on race condition
        db.rollback()
        if request.idempotency_key:
            existing = db.query(Task).filter(Task.idempotency_key == request.idempotency_key).first()
            if existing:
                return TaskResponse(task_id=existing.id, status=existing.status)
        raise HTTPException(status_code=500, detail="Database error during task creation")
    
    TASKS_SUBMITTED.inc()

    # 3. Enqueue task in Redis ONLY if immediate
    if is_immediate:
        queue.enqueue(new_task.id, priority=new_task.priority)

    # 4. Respond with task details
    return TaskResponse(task_id=new_task.id, status=new_task.status)

@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskResponse(
        task_id=task.id, 
        status=task.status,
        claimed_by=task.claimed_by,
        worker_host=task.worker_host
    )

@app.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Case 1: Terminal states
    if task.status in [TaskStatus.SUCCESS, TaskStatus.DEAD_LETTER, TaskStatus.CANCELLED]:
        raise HTTPException(status_code=409, detail=f"Task already in terminal state: {task.status}")

    # Case 2: QUEUED - cancel immediately
    if task.status == TaskStatus.QUEUED:
        task.status = TaskStatus.CANCELLED
        db.commit()
        TASKS_CANCELLED.inc()
        return {"status": "cancelled", "message": "Task cancelled immediately."}

    # Case 3: RUNNING - cooperative request (Choice B)
    if task.status == TaskStatus.RUNNING:
        task.cancel_requested = True
        db.commit()
        TASKS_CANCELLED.inc()
        return {"status": "cancellation_requested", "message": "Task cancellation requested."}

# --- ADMIN / DASHBOARD ENDPOINTS ---

@app.get("/admin/health")
def admin_health(api_key: str = Depends(get_api_key)):
    health = {"redis": "ok", "postgres": "ok"}
    try:
        queue.redis.ping()
    except Exception:
        health["redis"] = "error"
    
    return {
        "status": "ok" if all(v == "ok" for v in health.values()) else "degraded",
        "checks": health,
        "worker_capacity": settings.WORKER_CONCURRENCY
    }

@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    # Use count queries per status
    stats = {}
    for status in TaskStatus:
        count = db.query(Task).filter(Task.status == status).count()
        stats[status.value.lower()] = count
    return stats

@app.get("/admin/dead-letter")
def admin_dead_letter(limit: int = 10, offset: int = 0, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    tasks = (
        db.query(Task)
        .filter(Task.status == TaskStatus.DEAD_LETTER)
        .order_by(Task.updated_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        {
            "id": t.id,
            "task_type": t.task_type,
            "retry_count": t.retry_count,
            "last_error": t.last_error,
            "updated_at": t.updated_at
        }
        for t in tasks
    ]

@app.get("/admin/scheduled")
def admin_scheduled(limit: int = 10, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    tasks = (
        db.query(Task)
        .filter(Task.status == TaskStatus.SCHEDULED)
        .order_by(Task.run_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "task_type": t.task_type,
            "run_at": t.run_at,
            "created_at": t.created_at
        }
        for t in tasks
    ]

@app.get("/admin/tasks")
def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
    if search:
        query = query.filter(
            (Task.id.like(f"%{search}%")) | (Task.task_type.like(f"%{search}%"))
        )
    
    tasks = query.order_by(Task.updated_at.desc()).limit(limit).offset(offset).all()
    
    return [
        {
            "id": t.id,
            "task_type": t.task_type,
            "status": t.status,
            "priority": t.priority,
            "retry_count": t.retry_count,
            "claimed_by": t.claimed_by,
            "worker_host": t.worker_host,
            "timeout": t.timeout,
            "cancel_requested": t.cancel_requested,
            "run_at": t.run_at,
            "last_error": t.last_error,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "payload": t.payload
        }
        for t in tasks
    ]

@app.post("/admin/tasks/{task_id}/requeue")
def requeue_task(task_id: str, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task.status = TaskStatus.QUEUED
    task.retry_count = 0
    task.last_error = None
    task.claimed_by = None
    task.worker_host = None
    task.cancel_requested = False
    task.run_at = None
    db.commit()
    
    queue.enqueue(task.id, priority=task.priority)
    
    return {"status": "requeued", "message": f"Task {task_id} requeued successfully."}

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return HTMLResponse("<h1>Dashboard template not found at templates/dashboard.html</h1>", status_code=404)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)
