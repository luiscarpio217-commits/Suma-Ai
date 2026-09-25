"""
Corrections — fixing a saved entry without ever editing it.

What the user experiences as "edit" is invariant #2 under the hood: the
original journal entry is never touched. ledger.void_transaction posts its
mirror image, and ledger.record_transaction posts the corrected values as a
brand-new entry. Both halves go through the ledger engine, so balance and
immutability hold by construction.

Each ledger call commits on its own, so the two halves can't share one
database transaction. Everything that could make the second half refuse the
input is therefore checked before the first half runs.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import (
    Account, AccountType, EntrySource, Receipt, Transaction, TxnKind, TxnStatus, User,
)
from . import ledger


class CorrectionNotFound(Exception):
    pass


class AlreadyUndone(Exception):
    """Only a posted transaction can be corrected; a voided one is history."""


CATEGORY_TYPE_FOR = {TxnKind.money_out: AccountType.expense,
                     TxnKind.money_in: AccountType.income}


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
        raise AlreadyUndone(f"transaction {txn_id} is {original.status.value}")

    amount = Decimal(amount).quantize(ledger.TWO)
    if amount <= 0:
        raise ValueError("amount must be positive")
    category = db.get(Account, category_account_id)
    if category is None or category.user_id != user.id:
        raise ValueError("unknown category")
    if category.type != CATEGORY_TYPE_FOR[original.kind]:
        raise ValueError(f"{original.kind.value} category must be "
                         f"{CATEGORY_TYPE_FOR[original.kind].value}")
    method = method or original.method

    unchanged = (txn_date == original.txn_date
                 and amount == Decimal(original.amount)
                 and category.id == original.category_account_id
                 and counterparty == original.counterparty
                 and is_business == original.is_business
                 and method == original.method)
    if unchanged:
        return original  # a no-op save shouldn't add two entries to the history

    receipt = db.get(Receipt, original.receipt_id) if original.receipt_id else None
    ledger.void_transaction(db, user, original.id)
    return ledger.record_transaction(
        db, user, kind=original.kind, txn_date=txn_date, amount=amount,
        category_account_id=category.id, counterparty=counterparty,
        is_business=is_business, method=method, source=EntrySource.adjustment,
        receipt=receipt, memo=f"Correction of transaction {original.id}",
    )
