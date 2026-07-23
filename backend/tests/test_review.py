"""Needs-review queue — the human half of the confidence gate.

Confirming must post a balanced, receipt-linked transaction; rejecting must
post nothing; a failed confirm must leave the receipt in the queue. The
ledger invariants are never bypassed — everything goes through
ledger.record_transaction.
"""
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.models import (
    Account, EntrySource, JournalEntry, JournalLine,
    Receipt, ReceiptStatus, Transaction, TxnStatus,
)
from app.services import review


def cat(db, user, code):
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def make_receipt(db, user, *, extracted=None, status=ReceiptStatus.needs_review,
                 confidence=0.4):
    r = Receipt(user_id=user.id, file_path="/nonexistent/r.jpg", source="photo",
                extracted_json=json.dumps(extracted if extracted is not None else {}),
                confidence=confidence, status=status)
    db.add(r)
    db.commit()
    return r


def ledger_balances(db):
    debit = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    return Decimal(debit) == Decimal(credit)


def test_pending_lists_only_needs_review(db, user):
    keep = make_receipt(db, user)
    make_receipt(db, user, status=ReceiptStatus.auto_posted)
    make_receipt(db, user, status=ReceiptStatus.posted)
    make_receipt(db, user, status=ReceiptStatus.rejected)
    assert [r.id for r in review.pending_receipts(db, user)] == [keep.id]


def test_draft_survives_corrupt_extraction(db, user):
    r = make_receipt(db, user)
    r.extracted_json = "not json {{"
    d = review.receipt_draft(r)
    assert d["merchant"] == ""
    assert d["amount"] == 0.0
    assert d["date"] is None
    assert d["is_business"] is False


def test_confirm_posts_balanced_txn_and_marks_receipt_posted(db, user):
    r = make_receipt(db, user, extracted={"merchant": "Home Depot", "amount": 84.5})
    txn = review.confirm_receipt(
        db, user, r.id, amount=Decimal("84.50"), txn_date=date(2026, 7, 20),
        category_account_id=cat(db, user, "5022").id,
        counterparty="Home Depot", is_business=True)
    assert txn.status == TxnStatus.posted
    assert txn.receipt_id == r.id
    assert r.status == ReceiptStatus.posted
    assert db.get(JournalEntry, txn.entry_id).source == EntrySource.receipt
    assert ledger_balances(db)


def test_confirm_or_reject_twice_is_refused(db, user):
    r = make_receipt(db, user)
    review.confirm_receipt(db, user, r.id, amount=Decimal("10.00"),
                           txn_date=date.today(),
                           category_account_id=cat(db, user, "6010").id)
    with pytest.raises(review.AlreadyHandled):
        review.confirm_receipt(db, user, r.id, amount=Decimal("10.00"),
                               txn_date=date.today(),
                               category_account_id=cat(db, user, "6010").id)
    with pytest.raises(review.AlreadyHandled):
        review.reject_receipt(db, user, r.id)
    # only the first confirm posted anything
    assert db.query(Transaction).count() == 1


def test_reject_posts_nothing(db, user):
    r = make_receipt(db, user)
    review.reject_receipt(db, user, r.id)
    assert r.status == ReceiptStatus.rejected
    assert db.query(JournalLine).count() == 0
    assert db.query(Transaction).count() == 0
    assert review.pending_receipts(db, user) == []


def test_failed_confirm_leaves_receipt_in_queue(db, user):
    r = make_receipt(db, user)
    with pytest.raises(ValueError):
        review.confirm_receipt(db, user, r.id, amount=Decimal("10.00"),
                               txn_date=date.today(),
                               # income category — money_out must refuse it
                               category_account_id=cat(db, user, "4000").id)
    assert r.status == ReceiptStatus.needs_review
    assert [x.id for x in review.pending_receipts(db, user)] == [r.id]
    assert db.query(JournalLine).count() == 0


def test_unknown_or_foreign_receipt_not_found(db, user):
    with pytest.raises(review.ReviewNotFound):
        review.reject_receipt(db, user, 999)


def test_review_routes_registered():
    from app.main import app
    assert app.url_path_for("list_pending") == "/api/review"
    assert app.url_path_for("confirm", receipt_id=1) == "/api/review/1/confirm"
    assert app.url_path_for("reject", receipt_id=1) == "/api/review/1/reject"
    assert app.url_path_for("receipt_image", receipt_id=1) == "/api/review/1/image"
