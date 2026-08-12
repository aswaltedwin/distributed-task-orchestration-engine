import logging
import json
import datetime
import os
import socket

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "host": socket.gethostname(),
            "pid": os.getpid()
        }
        
        # Inject custom fields if present in extra
        if hasattr(record, "task_id"):
            log_record["task_id"] = record.task_id
        if hasattr(record, "worker_id"):
            log_record["worker_id"] = record.worker_id
        if hasattr(record, "event"):
            log_record["event"] = record.event
        if hasattr(record, "retry_count"):
            log_record["retry_count"] = record.retry_count

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)

def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
    
    # Silence verbose 3rd party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
