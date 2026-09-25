from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import DashboardOut
from ..services import ledger
from .deps import current_user, require_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_key)])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(year: int | None = None, month: int | None = None,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    today = date.today()
    return ledger.month_summary(db, user, year or today.year, month or today.month)
