"""
Ledger service — the accounting engine.

Rules enforced here, not in the UI:
1. Every journal entry balances: sum(debits) == sum(credits). Always.
2. Entries are immutable. A mistake is fixed by a reversing entry + a new entry.
3. Cash-basis: we recognize money when it moves (what sole proprietors file on).

Simple surface mapping:
    money_out  ->  debit  expense category   / credit Cash
    money_in   ->  debit  Cash               / credit income category
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Account, AccountType, EntrySource, JournalEntry, JournalLine,
    Receipt, Transaction, TxnKind, TxnStatus, User,
)

TWO = Decimal("0.01")


class UnbalancedEntry(Exception):
    pass


def _cash_account(db: Session, user_id: int) -> Account:
    return db.query(Account).filter_by(user_id=user_id, code="1000").one()


def _post_entry(db: Session, user_id: int, entry_date: date, memo: str,
                source: EntrySource, lines: list[tuple[int, Decimal, Decimal]],
                reverses_id: int | None = None) -> JournalEntry:
    """lines = [(account_id, debit, credit), ...] — must balance."""
    total_debit = sum((d for _, d, _ in lines), Decimal("0"))
    total_credit = sum((c for _, _, c in lines), Decimal("0"))
    if total_debit.quantize(TWO) != total_credit.quantize(TWO):
        raise UnbalancedEntry(f"debits {total_debit} != credits {total_credit}")
    entry = JournalEntry(user_id=user_id, entry_date=entry_date, memo=memo,
                         source=source, reverses_id=reverses_id)
    db.add(entry)
    db.flush()
    for account_id, debit, credit in lines:
        db.add(JournalLine(entry_id=entry.id, account_id=account_id,
                           debit=debit, credit=credit))
    return entry


def record_transaction(db: Session, user: User, *, kind: TxnKind, txn_date: date,
                       amount: Decimal, category_account_id: int,
                       counterparty: str = "", is_business: bool = False,
                       method: str = "cash", source: EntrySource = EntrySource.manual,
                       receipt: Receipt | None = None, memo: str = "") -> Transaction:
    if amount <= 0:
        raise ValueError("amount must be positive")
    amount = Decimal(amount).quantize(TWO)
    cash = _cash_account(db, user.id)
    category = db.get(Account, category_account_id)
    if category is None or category.user_id != user.id:
        raise ValueError("unknown category")

    if kind == TxnKind.money_out:
        if category.type != AccountType.expense:
            raise ValueError("money_out category must be an expense category")
        lines = [(category.id, amount, Decimal("0")), (cash.id, Decimal("0"), amount)]
    else:
        if category.type != AccountType.income:
            raise ValueError("money_in category must be an income category")
        lines = [(cash.id, amount, Decimal("0")), (category.id, Decimal("0"), amount)]

    entry = _post_entry(db, user.id, txn_date, memo or counterparty, source, lines)
    txn = Transaction(
        user_id=user.id, entry_id=entry.id, kind=kind, txn_date=txn_date,
        counterparty=counterparty, amount=amount, category_account_id=category.id,
        is_business=is_business, method=method,
        receipt_id=receipt.id if receipt else None,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def void_transaction(db: Session, user: User, txn_id: int) -> Transaction:
    """Fixing a mistake: post the mirror-image entry, mark the txn voided.
    Nothing is ever deleted — the audit trail stays intact."""
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.user_id != user.id:
        raise ValueError("transaction not found")
    if txn.status == TxnStatus.voided:
        return txn
    original = db.get(JournalEntry, txn.entry_id)
    mirror = [(l.account_id, Decimal(l.credit), Decimal(l.debit)) for l in original.lines]
    reversal = _post_entry(db, user.id, date.today(),
                           f"Reversal of entry {original.id}",
                           EntrySource.reversal, mirror, reverses_id=original.id)
    txn.status = TxnStatus.voided
    txn.voided_by_entry_id = reversal.id
    db.commit()
    db.refresh(txn)
    return txn


def month_summary(db: Session, user: User, year: int, month: int) -> dict:
    """The four numbers on the dashboard:
    came in / went out / what's left / set aside for taxes."""
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    q = (db.query(Transaction)
           .filter(Transaction.user_id == user.id,
                   Transaction.status == TxnStatus.posted,
                   Transaction.txn_date >= month_start,
                   Transaction.txn_date < month_end))
    money_in = Decimal("0")
    money_out = Decimal("0")
    biz_in = Decimal("0")
    biz_out = Decimal("0")
    for t in q:
        amt = Decimal(t.amount)
        if t.kind == TxnKind.money_in:
            money_in += amt
            if t.is_business:
                biz_in += amt
        else:
            money_out += amt
            if t.is_business:
                biz_out += amt
    net = money_in - money_out
    biz_profit = biz_in - biz_out
    set_aside = (biz_profit * Decimal(str(user.tax_set_aside_pct))).quantize(TWO)
    if set_aside < 0:
        set_aside = Decimal("0.00")
    return {
        "year": year, "month": month,
        "money_in": float(money_in), "money_out": float(money_out),
        "net": float(net),
        "business_profit": float(biz_profit),
        "tax_set_aside": float(set_aside),
    }
