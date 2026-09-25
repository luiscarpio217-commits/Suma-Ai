"""Edit = reversal + new entry. The original journal entry is never touched,
bad input never leaves an entry undone without its replacement, and the
dashboard only ever counts the corrected values."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.models import (
    Account, EntrySource, JournalEntry, JournalLine, Receipt, ReceiptStatus,
    Transaction, TxnKind, TxnStatus,
)
from app.services import corrections, ledger


def cat(db, user, code):
    return db.query(Account).filter_by(user_id=user.id, code=code).one()


def ledger_balances(db):
    debit = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    return Decimal(debit) == Decimal(credit)


def lines_of(db, entry_id):
    return sorted((l.account_id, Decimal(l.debit), Decimal(l.credit))
                  for l in db.query(JournalLine).filter_by(entry_id=entry_id))


def spend(db, user, amount="40.00", code="5009", day=date(2026, 7, 20), **kw):
    return ledger.record_transaction(
        db, user, kind=TxnKind.money_out, txn_date=day, amount=Decimal(amount),
        category_account_id=cat(db, user, code).id, **kw)


def fix(db, user, txn, **changes):
    values = dict(txn_date=txn.txn_date, amount=Decimal(txn.amount),
                  category_account_id=txn.category_account_id,
                  counterparty=txn.counterparty, is_business=txn.is_business)
    values.update(changes)
    return corrections.correct_transaction(db, user, txn.id, **values)


def test_correction_reverses_original_and_posts_new(db, user):
    original = spend(db, user, counterparty="Shell", is_business=True)
    original_entry, original_lines = original.entry_id, lines_of(db, original.entry_id)

    new = fix(db, user, original, amount=Decimal("45.00"),
              category_account_id=cat(db, user, "5022").id)

    db.refresh(original)
    assert original.status == TxnStatus.voided
    assert original.voided_by_entry_id is not None
    assert new.id != original.id and new.status == TxnStatus.posted
    assert Decimal(new.amount) == Decimal("45.00")
    assert new.kind == TxnKind.money_out
    # original entry + reversal + new entry, two lines each; nothing edited
    assert db.query(JournalEntry).count() == 3
    assert db.query(JournalLine).count() == 6
    assert lines_of(db, original_entry) == original_lines
    assert ledger_balances(db)


def test_dashboard_counts_only_corrected_values(db, user):
    original = spend(db, user, amount="200.00", day=date(2026, 7, 6), is_business=True)
    fix(db, user, original, amount=Decimal("150.00"), txn_date=date(2026, 8, 2))
    assert ledger.month_summary(db, user, 2026, 7)["money_out"] == 0.0
    assert ledger.month_summary(db, user, 2026, 8)["money_out"] == 150.0


def test_correction_keeps_receipt_and_records_where_it_came_from(db, user):
    receipt = Receipt(user_id=user.id, file_path="/x.jpg", status=ReceiptStatus.posted)
    db.add(receipt)
    db.commit()
    original = spend(db, user, receipt=receipt)
    new = fix(db, user, original, counterparty="Home Depot")
    entry = db.get(JournalEntry, new.entry_id)
    assert new.receipt_id == receipt.id
    assert entry.source == EntrySource.adjustment
    assert entry.memo == f"Correction of transaction {original.id}"


def test_money_in_stays_money_in(db, user):
    income = ledger.record_transaction(
        db, user, kind=TxnKind.money_in, txn_date=date(2026, 7, 21),
        amount=Decimal("500.00"), category_account_id=cat(db, user, "4000").id)
    new = fix(db, user, income, amount=Decimal("550.00"))
    assert new.kind == TxnKind.money_in
    assert ledger.month_summary(db, user, 2026, 7)["money_in"] == 550.0
    with pytest.raises(ValueError):  # an expense category can't hold money in
        fix(db, user, new, category_account_id=cat(db, user, "6010").id)


@pytest.mark.parametrize("bad", [
    {"category_code": "4000"},          # income category for money out
    {"category_account_id": 99999},     # no such category
    {"amount": Decimal("0")},
    {"amount": Decimal("-5.00")},
])
def test_bad_input_leaves_original_untouched(db, user, bad):
    original = spend(db, user)
    changes = dict(bad)
    if "category_code" in changes:
        changes["category_account_id"] = cat(db, user, changes.pop("category_code")).id
    with pytest.raises(ValueError):
        fix(db, user, original, **changes)
    db.refresh(original)
    assert original.status == TxnStatus.posted
    assert db.query(JournalLine).count() == 2
    assert db.query(Transaction).count() == 1


def test_undone_entry_cannot_be_corrected(db, user):
    original = spend(db, user)
    ledger.void_transaction(db, user, original.id)
    with pytest.raises(corrections.AlreadyUndone):
        fix(db, user, original, amount=Decimal("41.00"))


def test_unchanged_save_posts_nothing(db, user):
    original = spend(db, user, counterparty="Shell")
    assert fix(db, user, original).id == original.id
    assert original.status == TxnStatus.posted
    assert db.query(JournalLine).count() == 2


def test_unknown_transaction_not_found(db, user):
    with pytest.raises(corrections.CorrectionNotFound):
        corrections.correct_transaction(
            db, user, 999, txn_date=date.today(), amount=Decimal("1"),
            category_account_id=cat(db, user, "6010").id)


def test_correct_endpoint(client, db, user):
    original = spend(db, user)
    body = {"txn_date": "2026-07-20", "amount": "42.00",
            "category_account_id": cat(db, user, "5009").id}

    r = client.post(f"/api/transactions/{original.id}/correct", json=body)
    assert r.status_code == 200
    assert r.json()["amount"] == "42.00" and r.json()["id"] != original.id

    assert client.post(f"/api/transactions/{original.id}/correct",
                       json=body).status_code == 409          # already undone
    assert client.post("/api/transactions/999/correct", json=body).status_code == 404
    new_id = r.json()["id"]
    wrong = {**body, "category_account_id": cat(db, user, "4000").id}
    assert client.post(f"/api/transactions/{new_id}/correct",
                       json=wrong).status_code == 400
    assert client.post(f"/api/transactions/{new_id}/correct",
                       json={**body, "amount": "0"}).status_code == 422
    assert client.post(f"/api/transactions/{new_id}/correct", json=body,
                       headers={"X-API-Key": "wrong"}).status_code == 401
    assert ledger_balances(db)
