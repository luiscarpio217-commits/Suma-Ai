"""Quarterly tax card: the next 1040-ES due date (always the 15th) and the
set-aside added up, month by month as each board showed it, for the months
that payment covers."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import Account, TxnKind
from app.services import ledger, tax_card


def cat(db, user, code):
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def earned(db, user, day, amount):
    return ledger.record_transaction(
        db, user, kind=TxnKind.money_in, txn_date=day, amount=Decimal(amount),
        category_account_id=cat(db, user, "4000").id, is_business=True)


def spent(db, user, day, amount):
    return ledger.record_transaction(
        db, user, kind=TxnKind.money_out, txn_date=day, amount=Decimal(amount),
        category_account_id=cat(db, user, "5022").id, is_business=True)


@pytest.mark.parametrize("today, due, tax_year, months", [
    (date(2027, 1, 1), date(2027, 1, 15), 2026, (9, 12)),
    (date(2027, 1, 15), date(2027, 1, 15), 2026, (9, 12)),   # due today still counts
    (date(2027, 1, 16), date(2027, 4, 15), 2027, (1, 3)),
    (date(2027, 4, 15), date(2027, 4, 15), 2027, (1, 3)),
    (date(2027, 4, 16), date(2027, 6, 15), 2027, (4, 5)),
    (date(2027, 6, 15), date(2027, 6, 15), 2027, (4, 5)),
    (date(2027, 6, 16), date(2027, 9, 15), 2027, (6, 8)),
    (date(2027, 9, 16), date(2028, 1, 15), 2027, (9, 12)),   # Jan 15, 2028 is a Saturday
    (date(2027, 12, 31), date(2028, 1, 15), 2027, (9, 12)),
])
def test_next_payment(today, due, tax_year, months):
    p = tax_card.next_payment(today)
    assert (p.due, p.tax_year, (p.first_month, p.last_month)) == (due, tax_year, months)


def test_every_day_points_at_a_15th_after_its_months_end():
    day = date(2026, 1, 1)
    while day < date(2029, 1, 1):
        p = tax_card.next_payment(day)
        assert p.due.day == 15 and p.due >= day
        assert p.due > date(p.tax_year, p.last_month, 28)       # the months end first
        assert p.due - day <= timedelta(days=121)               # never skips a payment
        day += timedelta(days=1)


def test_total_adds_each_month_as_shown_so_a_loss_month_adds_zero(db, user):
    earned(db, user, date(2026, 8, 20), "5000")        # August belongs to the Sep 15 payment
    earned(db, user, date(2026, 9, 5), "1000")
    spent(db, user, date(2026, 9, 6), "200")           # September: 25% of 800 = 200
    spent(db, user, date(2026, 10, 2), "1000")         # October: a loss, shown as 0
    earned(db, user, date(2026, 11, 3), "400")         # November: 25% of 400 = 100
    earned(db, user, date(2026, 12, 1), "800")         # December hasn't happened yet
    card = tax_card.tax_card(db, user, date(2026, 11, 10))
    assert card["due_date"] == date(2027, 1, 15)
    assert (card["period_start"], card["period_end"]) == (date(2026, 9, 1), date(2026, 12, 31))
    assert card["set_aside"] == 300.0  # not 25% of the three months' net (50.0)
    shown = [ledger.month_summary(db, user, 2026, m)["tax_set_aside"] for m in (9, 10, 11)]
    assert shown == [200.0, 0.0, 100.0]


def test_early_january_still_counts_the_whole_previous_period(db, user):
    for month in (9, 10, 11, 12):
        earned(db, user, date(2026, month, 15), "100")   # 25.00 each
    earned(db, user, date(2027, 1, 3), "999")            # belongs to the April payment
    card = tax_card.tax_card(db, user, date(2027, 1, 10))
    assert card["due_date"] == date(2027, 1, 15)
    assert card["set_aside"] == 100.0


def test_undone_entries_dont_count(db, user):
    earned(db, user, date(2027, 4, 20), "400")
    undone = earned(db, user, date(2027, 5, 2), "4000")
    ledger.void_transaction(db, user, undone.id)
    card = tax_card.tax_card(db, user, date(2027, 5, 31))
    assert (card["period_start"], card["period_end"]) == (date(2027, 4, 1), date(2027, 5, 31))
    assert card["set_aside"] == 100.0


def test_tax_card_endpoint(client, db, user):
    body = client.get("/api/tax-card").json()
    expected = tax_card.next_payment(date.today())
    assert body["due_date"] == expected.due.isoformat()
    assert body["period_start"] == date(expected.tax_year, expected.first_month, 1).isoformat()
    assert body["set_aside"] == 0.0
