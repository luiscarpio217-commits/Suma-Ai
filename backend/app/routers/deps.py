"""Shared dependencies. v0 is single-user with a static API key.
Multi-user auth (JWT + registration) is a Phase 2 task — see CLAUDE.md."""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User


def require_key(x_api_key: str = Header(default="")):
    if x_api_key != settings.suma_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")


def current_user(db: Session = Depends(get_db)) -> User:
    user = db.query(User).first()
    if user is None:
        raise HTTPException(status_code=500, detail="database not seeded")
    return user
