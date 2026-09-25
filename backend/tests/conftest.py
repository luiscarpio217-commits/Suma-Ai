"""Shared fixtures for service-level and API tests.

test_ledger.py keeps its own identical copies on purpose — that file is the
invariant suite and stays self-contained; module-level fixtures shadow these.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.seed import seed


@pytest.fixture()
def db():
    # One shared in-memory connection, usable from the API client's worker thread.
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def user(db):
    return seed(db)


@pytest.fixture()
def client(db, user):
    """HTTP client against the real app, wired to the test database.
    Not used as a context manager, so the startup hook never touches suma.db."""
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, headers={"X-API-Key": settings.suma_api_key})
    app.dependency_overrides.clear()
