"""
Corrections — fixing a saved entry without ever editing it.

What the user experiences as "edit" is invariant #2 under the hood: the
original journal entry is never touched. ledger.void_transaction posts its
mirror image, and ledger.record_transaction posts the corrected values as a
brand-new entry. Both halves go through the ledger engine, so balance and
immutability hold by construction — and they share one database transaction,
so a correction lands completely or not at all.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import EntrySource, Receipt, Transaction, TxnStatus, User
from . import ledger


class CorrectionNotFound(Exception):
    pass


def correct_transaction(db: Session, user: User, txn_id: int, *, txn_date: date,
                        amount: Decimal, category_account_id: int,
                        counterparty: str = "", is_business: bool = False,
                        method: str | None = None) -> Transaction:
    """Returns the replacement transaction, or the original if nothing changed.
    Money in stays money in and money out stays money out."""
    original = db.get(Transaction, txn_id)
    if original is None or original.user_id != user.id:
        raise CorrectionNotFound(f"transaction {txn_id} not found")
    if original.status != TxnStatus.posted:
        raise ledger.AlreadyVoided(f"transaction {txn_id} was already undone")
    method = method or original.method

    unchanged = (txn_date == original.txn_date
                 and Decimal(amount).quantize(ledger.TWO) == Decimal(original.amount)
                 and category_account_id == original.category_account_id
                 and counterparty == original.counterparty
                 and is_business == original.is_business
                 and method == original.method)
    if unchanged:
        return original  # a no-op save shouldn't add two entries to the history

    receipt = db.get(Receipt, original.receipt_id) if original.receipt_id else None
    try:
        ledger.void_transaction(db, user, original.id, commit=False)
        replacement = ledger.record_transaction(
            db, user, kind=original.kind, txn_date=txn_date, amount=amount,
            category_account_id=category_account_id, counterparty=counterparty,
            is_business=is_business, method=method, source=EntrySource.adjustment,
            receipt=receipt, memo=f"Correction of transaction {original.id}",
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()  # neither half lands; the original stays exactly as it was
        raise
    db.refresh(replacement)
    return replacement
