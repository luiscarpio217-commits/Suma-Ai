"""Ledger invariants — the tests that matter most in a money app."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import JournalLine, TxnKind, TxnStatus
from app.seed import seed
from app.services import ledger


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


def cat(db, user, code):
    from app.models import Account
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def ledger_balances(db):
    debit = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    return Decimal(debit) == Decimal(credit)


def test_money_out_posts_balanced_entry(db, user):
    txn = ledger.record_transaction(
        db, user, kind=TxnKind.money_out, txn_date=date(2026, 7, 20),
        amount=Decimal("40.00"), category_account_id=cat(db, user, "5009").id,
        counterparty="Shell", is_business=True)
    assert txn.status == TxnStatus.posted
    assert ledger_balances(db)


def test_money_in_posts_balanced_entry(db, user):
    ledger.record_transaction(
        db, user, kind=TxnKind.money_in, txn_date=date(2026, 7, 21),
        amount=Decimal("500.00"), category_account_id=cat(db, user, "4000").id,
        counterparty="Client A", is_business=True)
    assert ledger_balances(db)


def test_void_creates_reversal_not_deletion(db, user):
    txn = ledger.record_transaction(
        db, user, kind=TxnKind.money_out, txn_date=date(2026, 7, 20),
        amount=Decimal("99.00"), category_account_id=cat(db, user, "6010").id)
    voided = ledger.void_transaction(db, user, txn.id)
    assert voided.status == TxnStatus.voided
    assert voided.voided_by_entry_id is not None
    # both original and reversal lines exist; ledger still balances
    assert db.query(JournalLine).count() == 4
    assert ledger_balances(db)


def test_unbalanced_entry_is_impossible(db, user):
    with pytest.raises(ledger.UnbalancedEntry):
        ledger._post_entry(db, user.id, date.today(), "bad", 
                           ledger.EntrySource.manual,
                           [(cat(db, user, "1000").id, Decimal("10"), Decimal("0"))])


def test_wrong_category_type_rejected(db, user):
    with pytest.raises(ValueError):
        ledger.record_transaction(
            db, user, kind=TxnKind.money_out, txn_date=date.today(),
            amount=Decimal("10.00"), category_account_id=cat(db, user, "4000").id)


def test_dashboard_four_numbers(db, user):
    biz_income = cat(db, user, "4000")
    gas = cat(db, user, "5009")
    groceries = cat(db, user, "6010")
    ledger.record_transaction(db, user, kind=TxnKind.money_in, txn_date=date(2026, 7, 5),
                              amount=Decimal("1000"), category_account_id=biz_income.id,
                              is_business=True)
    ledger.record_transaction(db, user, kind=TxnKind.money_out, txn_date=date(2026, 7, 6),
                              amount=Decimal("200"), category_account_id=gas.id,
                              is_business=True)
    ledger.record_transaction(db, user, kind=TxnKind.money_out, txn_date=date(2026, 7, 7),
                              amount=Decimal("150"), category_account_id=groceries.id,
                              is_business=False)
    s = ledger.month_summary(db, user, 2026, 7)
    assert s["money_in"] == 1000.0
    assert s["money_out"] == 350.0
    assert s["net"] == 650.0
    assert s["business_profit"] == 800.0
    assert s["tax_set_aside"] == 200.0  # 25% of business profit


def test_voided_txns_excluded_from_dashboard(db, user):
    gas = cat(db, user, "5009")
    t = ledger.record_transaction(db, user, kind=TxnKind.money_out,
                                  txn_date=date(2026, 7, 6), amount=Decimal("200"),
                                  category_account_id=gas.id, is_business=True)
    ledger.void_transaction(db, user, t.id)
    s = ledger.month_summary(db, user, 2026, 7)
    assert s["money_out"] == 0.0
