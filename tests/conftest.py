import os
import pytest

# Ensure SQLite and test environment variables are set before any app imports
os.environ.setdefault('API_KEY', 'supersecret')

# If postgres is not running locally, redirect to SQLite for local tests
if 'postgres' in os.environ.get('DATABASE_URL', '') or not os.environ.get('DATABASE_URL'):
    os.environ['DATABASE_URL'] = 'sqlite:///test_suite.db'

from app.database import engine, Base
from app.worker import shutdown_event
from app.metrics import (
    TASKS_SUBMITTED,
    TASKS_SUCCESS,
    TASKS_FAILED,
    TASKS_CANCELLED,
    TASKS_RETRIED,
    TASKS_ACTIVE
)

@pytest.fixture(autouse=True)
def reset_test_state():
    # Ensure tables exist
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    # 1. Reset worker shutdown state
    shutdown_event.clear()
    
    # 2. Reset prometheus metrics counters between tests
    for metric in [TASKS_SUBMITTED, TASKS_SUCCESS, TASKS_FAILED, TASKS_CANCELLED, TASKS_RETRIED]:
        metric._value.set(0)
    TASKS_ACTIVE.set(0)
    
    yield
    
    # Clean up after test
    shutdown_event.clear()
