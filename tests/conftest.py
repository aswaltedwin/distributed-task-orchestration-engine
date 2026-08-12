import pytest

@pytest.fixture(autouse=True)
def clean_db():
    try:
        from app.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass
    yield
