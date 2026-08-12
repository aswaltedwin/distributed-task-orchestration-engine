from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Counters
TASKS_SUBMITTED = Counter(
    "tasks_submitted_total", 
    "Total number of tasks submitted to the API"
)
TASKS_SUCCESS = Counter(
    "tasks_success_total", 
    "Total number of successfully completed tasks"
)
TASKS_FAILED = Counter(
    "tasks_failed_total", 
    "Total number of task execution attempts that failed"
)
TASKS_CANCELLED = Counter(
    "tasks_cancelled_total", 
    "Total number of tasks cancelled"
)
TASKS_RETRIED = Counter(
    "tasks_retried_total", 
    "Total number of task retries triggered"
)

# Gauges
TASKS_ACTIVE = Gauge(
    "tasks_active", 
    "Number of tasks currently being processed by workers"
)

# Histograms
TASK_EXECUTION_DURATION = Histogram(
    "task_execution_seconds", 
    "Duration of task execution in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600)
)

def get_metrics_report():
    """Returns the current metrics in Prometheus text format."""
    return generate_latest(), CONTENT_TYPE_LATEST
