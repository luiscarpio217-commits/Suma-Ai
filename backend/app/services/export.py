"""
Accountant Export.

Produces the year-end package a tax preparer actually wants:
1. Schedule C summary — business income and expenses grouped by Schedule C line.
2. Full transaction listing — every posted transaction with category and receipt ref.

This is the anti-shoebox feature.
"""
import csv
import io
from datetime import date

from sqlalchemy.orm import Session

from ..models import Transaction, TxnKind, TxnStatus, User


def schedule_c_summary_csv(db: Session, user: User, year: int) -> str:
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    txns = (db.query(Transaction)
              .filter(Transaction.user_id == user.id,
                      Transaction.status == TxnStatus.posted,
                      Transaction.is_business.is_(True),
                      Transaction.txn_date >= start,
                      Transaction.txn_date < end)
              .all())

    gross_income = sum(float(t.amount) for t in txns if t.kind == TxnKind.money_in)
    by_line: dict[str, tuple[str, float]] = {}
    for t in txns:
        if t.kind != TxnKind.money_out:
            continue
        line = t.category.schedule_c_line or "27a"
        name = t.category.name_en
        prev = by_line.get(line, (name, 0.0))
        by_line[line] = (prev[0], prev[1] + float(t.amount))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Schedule C summary — {year}", ""])
    w.writerow(["Line", "Category", "Amount"])
    w.writerow(["1", "Gross receipts", f"{gross_income:.2f}"])
    total_exp = 0.0
    for line in sorted(by_line, key=lambda s: (len(s), s)):
        name, amt = by_line[line]
        total_exp += amt
        w.writerow([line, name, f"{amt:.2f}"])
    w.writerow(["28", "Total expenses", f"{total_exp:.2f}"])
    w.writerow(["31", "Net profit (loss)", f"{gross_income - total_exp:.2f}"])
    return buf.getvalue()


def transactions_csv(db: Session, user: User, year: int) -> str:
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    txns = (db.query(Transaction)
              .filter(Transaction.user_id == user.id,
                      Transaction.txn_date >= start,
                      Transaction.txn_date < end)
              .order_by(Transaction.txn_date)
              .all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "In/Out", "Counterparty", "Amount", "Category",
                "Business", "Method", "Status", "Receipt"])
    for t in txns:
        w.writerow([
            t.txn_date.isoformat(),
            "in" if t.kind == TxnKind.money_in else "out",
            t.counterparty,
            f"{float(t.amount):.2f}",
            t.category.name_en,
            "yes" if t.is_business else "no",
            t.method,
            t.status.value,
            t.receipt_id or "",
        ])
    return buf.getvalue()
