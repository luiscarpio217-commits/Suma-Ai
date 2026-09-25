"""The two engine additions approved in PR #2, tested apart from
test_ledger.py so the seven original invariant tests stay exactly as written.

1. commit=False lets a caller put void_transaction and record_transaction in
   one database transaction (a correction lands both halves or neither).
   Leaving it out keeps the old commit-immediately behavior.
2. An entry can be undone only once. The refusal happens in the database,
   so two undos racing on the same entry can't both post a reversal.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Account, JournalLine, Transaction, TxnKind, TxnStatus, User
from app.seed import seed
from app.services import ledger


def cat(db, user, code):
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def ledger_balances(db):
    debit = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    return Decimal(debit) == Decimal(credit)


def spend(db, user, **kw):
    return ledger.record_transaction(
        db, user, kind=TxnKind.money_out, txn_date=date(2026, 7, 20),
        amount=Decimal("99.00"), category_account_id=cat(db, user, "6010").id, **kw)


def test_second_undo_is_refused(db, user):
    txn = spend(db, user)
    ledger.void_transaction(db, user, txn.id)
    with pytest.raises(ledger.AlreadyVoided):
        ledger.void_transaction(db, user, txn.id)
    assert db.query(JournalLine).count() == 4  # original + one reversal, no more
    assert ledger_balances(db)


def test_racing_undos_post_only_one_reversal(tmp_path):
    """A double tap: the second request has already loaded the entry (still
    posted) when the first request's undo commits. The second undo must be
    refused even though its own copy of the entry still says 'posted'."""
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    first, second = Session(engine), Session(engine)
    try:
        user = seed(first)
        txn_id = spend(first, user).id
        # Held for the whole race: a session only keeps loaded rows alive while
        # something references them, just as a request does mid-undo.
        stale_copy = second.get(Transaction, txn_id)
        assert stale_copy.status == TxnStatus.posted

        ledger.void_transaction(first, user, txn_id)
        assert stale_copy.status == TxnStatus.posted  # the second request can't know
        with pytest.raises(ledger.AlreadyVoided):
            ledger.void_transaction(second, second.get(User, user.id), txn_id)
        second.rollback()

        with Session(engine) as check:
            assert check.query(JournalLine).count() == 4
            assert ledger_balances(check)
    finally:
        first.close()
        second.close()
        engine.dispose()


def test_commit_false_leaves_the_commit_to_the_caller(db, user):
    txn = spend(db, user, commit=False)
    assert txn.id is not None  # flushed, so the caller can use it
    db.rollback()
    assert db.query(Transaction).count() == 0
    assert db.query(JournalLine).count() == 0

    kept = spend(db, user)
    ledger.void_transaction(db, user, kept.id, commit=False)
    db.rollback()
    db.refresh(kept)
    assert kept.status == TxnStatus.posted
    assert db.query(JournalLine).count() == 2


def test_default_still_commits_immediately(db, user):
    txn = spend(db, user)
    db.rollback()  # nothing pending: record_transaction already committed
    assert db.get(Transaction, txn.id) is not None
    ledger.void_transaction(db, user, txn.id)
    db.rollback()
    assert db.get(Transaction, txn.id).status == TxnStatus.voided
