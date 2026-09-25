"""
Quarterly tax card — when the next estimated-tax payment is due, and how much
"Guarde para impuestos" has added up for the months that payment covers.

Due dates are the four Form 1040-ES payments, always shown on the 15th. When
the 15th falls on a weekend or holiday the IRS allows the next business day,
so the 15th is never late — at worst a day or two early.

The total adds up each month's set-aside exactly as that month's board showed
it (ledger.month_summary), so a month with a loss adds $0 instead of lowering
the total. It's an estimate of what to set aside, not the tax owed; the card
says so.
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from ..models import User
from . import ledger

DUE_DAY = 15

# (first month, last month, due month, due in the next calendar year?)
PAYMENT_PERIODS = (
    (1, 3, 4, False),   # Jan–Mar -> Apr 15
    (4, 5, 6, False),   # Apr–May -> Jun 15
    (6, 8, 9, False),   # Jun–Aug -> Sep 15
    (9, 12, 1, True),   # Sep–Dec -> Jan 15 of the next year
)


class Payment(NamedTuple):
    due: date
    tax_year: int
    first_month: int
    last_month: int


def next_payment(today: date) -> Payment:
    """The first payment due on or after today (a payment due today counts)."""
    for tax_year in (today.year - 1, today.year):
        for first, last, due_month, next_year in PAYMENT_PERIODS:
            due = date(tax_year + next_year, due_month, DUE_DAY)
            if due >= today:
                return Payment(due, tax_year, first, last)
    raise AssertionError("unreachable: a Sep–Dec payment is always due within a year")


def tax_card(db: Session, user: User, today: date) -> dict:
    payment = next_payment(today)
    total = Decimal("0")
    for month in range(payment.first_month, payment.last_month + 1):
        if (payment.tax_year, month) > (today.year, today.month):
            break  # hasn't happened yet
        shown = ledger.month_summary(db, user, payment.tax_year, month)["tax_set_aside"]
        total += Decimal(str(shown))
    last_day = calendar.monthrange(payment.tax_year, payment.last_month)[1]
    return {
        "due_date": payment.due,
        "period_start": date(payment.tax_year, payment.first_month, 1),
        "period_end": date(payment.tax_year, payment.last_month, last_day),
        "set_aside": float(total.quantize(ledger.TWO)),
    }
