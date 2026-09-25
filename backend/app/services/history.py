"""
Monthly history — the four numbers for months before this one.

Every month goes through ledger.month_summary, the same function behind the
dashboard, so a past month here always shows exactly what its board showed.
"""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Transaction, User
from . import ledger


def prior_months(db: Session, user: User, today: date, limit: int = 12) -> list[dict]:
    """Newest first, starting with last month and going back to the month of
    the user's first entry — at most `limit` months. Months with nothing in
    them after that first entry still appear, as zeros."""
    first = (db.query(func.min(Transaction.txn_date))
               .filter(Transaction.user_id == user.id).scalar())
    if first is None:
        return []
    months = []
    year, month = today.year, today.month
    for _ in range(limit):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        if (year, month) < (first.year, first.month):
            break
        months.append(ledger.month_summary(db, user, year, month))
    return months
