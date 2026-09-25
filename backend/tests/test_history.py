"""Monthly history: prior months' four numbers, identical to what each
month's board showed, from the first entry onward."""
from datetime import date, timedelta
from decimal import Decimal

from app.models import Account, TxnKind
from app.services import history, ledger


def cat(db, user, code):
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def entry(db, user, day, amount, code="5009", kind=TxnKind.money_out, business=True):
    return ledger.record_transaction(
        db, user, kind=kind, txn_date=day, amount=Decimal(amount),
        category_account_id=cat(db, user, code).id, is_business=business)


def months_of(rows):
    return [(r["year"], r["month"]) for r in rows]


def test_nothing_logged_means_no_history(db, user):
    assert history.prior_months(db, user, date(2026, 9, 25)) == []


def test_from_first_entry_to_last_month_newest_first(db, user):
    entry(db, user, date(2026, 6, 10), "100", code="4000", kind=TxnKind.money_in)
    entry(db, user, date(2026, 8, 3), "40")
    entry(db, user, date(2026, 9, 1), "999")  # this month: the board's job, not history's
    rows = history.prior_months(db, user, date(2026, 9, 25))
    assert months_of(rows) == [(2026, 8), (2026, 7), (2026, 6)]
    july = rows[1]
    assert (july["money_in"], july["money_out"], july["net"], july["tax_set_aside"]) == (0, 0, 0, 0)


def test_each_month_matches_its_board(db, user):
    entry(db, user, date(2026, 7, 5), "1000", code="4000", kind=TxnKind.money_in)
    entry(db, user, date(2026, 7, 6), "200")
    entry(db, user, date(2026, 7, 7), "150", code="6010", business=False)
    undone = entry(db, user, date(2026, 7, 8), "75")
    ledger.void_transaction(db, user, undone.id)
    [july] = history.prior_months(db, user, date(2026, 8, 1))
    assert july == ledger.month_summary(db, user, 2026, 7)
    assert (july["money_in"], july["money_out"], july["net"], july["tax_set_aside"]) == \
        (1000.0, 350.0, 650.0, 200.0)


def test_limit_and_year_boundary(db, user):
    entry(db, user, date(2024, 3, 1), "10")
    rows = history.prior_months(db, user, date(2027, 1, 10), limit=12)
    assert len(rows) == 12
    assert months_of(rows)[:2] == [(2026, 12), (2026, 11)]
    assert months_of(rows)[-1] == (2026, 1)


def test_history_endpoint(client, db, user):
    last_month = date.today().replace(day=1) - timedelta(days=1)  # its last day
    entry(db, user, last_month.replace(day=1), "25")
    rows = client.get("/api/history").json()
    assert months_of(rows) == [(last_month.year, last_month.month)]
    assert rows[0]["money_out"] == 25.0
    assert client.get("/api/history?months=0").status_code == 422
    assert client.get("/api/history?months=37").status_code == 422
