import time
import logging
from sqlalchemy.exc import OperationalError
from app.database import engine, Base
from app.models import Task # Ensure models are imported

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_init")

def init_db():
    retries = 10
    while retries > 0:
        try:
            logger.info("Attempting to initialize database tables...")
            Base.metadata.create_all(bind=engine)
            logger.info("Database initialization successful.")
            return
        except OperationalError as e:
            logger.warning(f"Database not ready yet... {e}")
            retries -= 1
            time.sleep(5)
    
    logger.error("Could not initialize database after multiple attempts.")
    exit(1)

if __name__ == "__main__":
    init_db()
