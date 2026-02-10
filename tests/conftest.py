import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.database as db
from app.main import create_app


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # important for in-memory SQLite across threads
    )
    return engine


@pytest.fixture(scope="session")
def TestingSessionLocal(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def create_test_tables(test_engine):
    # Make sure models are imported so Base knows about them
    import app.models  # noqa: F401

    db.Base.metadata.create_all(bind=test_engine)
    yield
    db.Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client(TestingSessionLocal):
    app = create_app()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db.get_db] = override_get_db

    return TestClient(app)