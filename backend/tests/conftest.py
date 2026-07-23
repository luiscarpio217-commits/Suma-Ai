"""Shared fixtures for service-level tests.

test_ledger.py keeps its own identical copies on purpose — that file is the
invariant suite and stays self-contained; module-level fixtures shadow these.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.seed import seed


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def user(db):
    return seed(db)
