from sqlalchemy import Column, String, DateTime, JSON, Integer, Enum, Text, Boolean
from app.database import Base
import datetime
import uuid
from enum import Enum as PyEnum

class TaskStatus(str, PyEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"
    SCHEDULED = "SCHEDULED"

class TaskPriority(str, PyEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    task_type = Column(String, index=True)
    payload = Column(JSON)
    status = Column(Enum(TaskStatus, native_enum=False), default=TaskStatus.QUEUED, nullable=False)
    priority = Column(Enum(TaskPriority, native_enum=False), default=TaskPriority.NORMAL, nullable=False)
    run_at = Column(DateTime, nullable=True)
    
    # Worker Attribution
    claimed_by = Column(String, index=True, nullable=True)
    worker_host = Column(String, nullable=True)
    
    timeout = Column(Integer, default=60, nullable=False)
    
    cancel_requested = Column(Boolean, default=False, nullable=False)
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    heartbeat_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
