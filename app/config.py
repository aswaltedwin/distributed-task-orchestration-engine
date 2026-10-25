from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    DATABASE_URL: str = 'postgresql://user:password@localhost:5432/taskdb'
    REDIS_URL: str = 'redis://localhost:6379/0'
    TASK_QUEUE: str = 'task_queue'
    PROCESSING_QUEUE: str = 'processing_queue'
    MAX_RETRIES: int = 3
    WORKER_CONCURRENCY: int = 3
    API_KEY: str = 'supersecret'
    RATE_LIMIT_PER_MINUTE: int = 60

settings = Settings()
