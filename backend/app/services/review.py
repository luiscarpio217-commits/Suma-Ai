"""
Needs-review queue service.

Receipts whose AI extraction fell below the confidence gate wait here until
the user confirms, edits, or rejects them — the human half of invariant #4
(never silently guess on someone's money).

Confirming posts through ledger.record_transaction like any other
transaction, so the balance and immutability invariants hold by
construction. Rejecting only flips the receipt's status; nothing is
ever deleted.
"""
import json
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import EntrySource, Receipt, ReceiptStatus, Transaction, TxnKind, User
from . import ledger


class ReviewNotFound(Exception):
    pass


class AlreadyHandled(Exception):
    """The receipt left the queue already (posted, auto-posted, or rejected)."""


DRAFT_DEFAULTS = {"merchant": "", "amount": 0.0, "date": None,
                  "category_code": "", "is_business": False, "note": ""}


def receipt_draft(receipt: Receipt) -> dict:
    """The stored AI extraction as a safe dict. Missing or corrupt JSON
    becomes an empty draft — the UI shows that as 'we couldn't read this
    one' and the user fills it in by hand."""
    try:
        data = json.loads(receipt.extracted_json or "{}")
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        data = {}
    draft = {key: data.get(key, default) for key, default in DRAFT_DEFAULTS.items()}
    try:
        draft["amount"] = float(draft["amount"] or 0)
    except (TypeError, ValueError):
        draft["amount"] = 0.0
    draft["is_business"] = bool(draft["is_business"])
    for key in ("merchant", "category_code", "note"):
        if not isinstance(draft[key], str):
            draft[key] = ""
    if draft["date"] is not None and not isinstance(draft["date"], str):
        draft["date"] = None
    return draft


def pending_receipts(db: Session, user: User) -> list[Receipt]:
    return (db.query(Receipt)
              .filter(Receipt.user_id == user.id,
                      Receipt.status == ReceiptStatus.needs_review)
              .order_by(Receipt.created_at.desc(), Receipt.id.desc())
              .all())


def _get_pending(db: Session, user: User, receipt_id: int) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None or receipt.user_id != user.id:
        raise ReviewNotFound(f"receipt {receipt_id} not found")
    if receipt.status != ReceiptStatus.needs_review:
        raise AlreadyHandled(f"receipt {receipt_id} is {receipt.status.value}")
    return receipt


def confirm_receipt(db: Session, user: User, receipt_id: int, *,
                    amount: Decimal, txn_date: date, category_account_id: int,
                    counterparty: str = "", is_business: bool = False,
                    method: str = "cash") -> Transaction:
    """User confirmed the (possibly edited) draft — post it for real.

    Receipts are money going out; money coming in is entered manually.
    The status flip rides record_transaction's commit, so either the
    transaction and the status land together or neither does.
    """
    receipt = _get_pending(db, user, receipt_id)
    receipt.status = ReceiptStatus.posted
    source = EntrySource.voice if receipt.source == "voice" else EntrySource.receipt
    try:
        return ledger.record_transaction(
            db, user, kind=TxnKind.money_out, txn_date=txn_date, amount=amount,
            category_account_id=category_account_id, counterparty=counterparty,
            is_business=is_business, method=method, source=source, receipt=receipt,
        )
    except Exception:
        db.rollback()  # keep the receipt in the queue if posting failed
        raise


def reject_receipt(db: Session, user: User, receipt_id: int) -> Receipt:
    """Not a real expense (blurry photo, duplicate, someone else's ticket).
    Nothing posts to the ledger; the receipt row stays for the record."""
    receipt = _get_pending(db, user, receipt_id)
    receipt.status = ReceiptStatus.rejected
    db.commit()
    return receipt
