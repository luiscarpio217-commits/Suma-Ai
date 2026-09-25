from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import export as export_svc
from .deps import current_user, require_key

router = APIRouter(prefix="/api/export", dependencies=[Depends(require_key)])


@router.get("/schedule-c.csv", response_class=PlainTextResponse)
def schedule_c(year: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    return export_svc.schedule_c_summary_csv(db, user, year or date.today().year)


@router.get("/transactions.csv", response_class=PlainTextResponse)
def transactions(year: int | None = None, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    return export_svc.transactions_csv(db, user, year or date.today().year)
