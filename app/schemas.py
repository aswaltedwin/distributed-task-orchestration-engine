from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
from app.models import TaskStatus, TaskPriority

class TaskCreateRequest(BaseModel):
    task_type: str
    payload: Dict[str, Any]
    run_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None
    priority: Optional[TaskPriority] = TaskPriority.NORMAL
    timeout: Optional[int] = 60

class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    claimed_by: Optional[str] = None
    worker_host: Optional[str] = None
