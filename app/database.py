from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

connect_args = {'check_same_thread': False} if 'sqlite' in settings.DATABASE_URL else {}
engine_kwargs = {'pool_pre_ping': True}
if 'sqlite' not in settings.DATABASE_URL:
    engine_kwargs.update({'pool_size': 10, 'max_overflow': 20})

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
