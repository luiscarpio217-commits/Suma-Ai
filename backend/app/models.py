"""
Suma data model.

Design principle: rigorous double-entry accounting UNDER the hood,
a dead-simple "money in / money out" surface ON TOP.

- JournalEntry / JournalLine  -> the immutable double-entry ledger (never edited, only reversed)
- Transaction                 -> the user-facing simple event, linked 1:1 to a journal entry
- Account                     -> chart of accounts, bilingual names, Schedule C line mapping
- Receipt                     -> captured photo/voice artifact + AI extraction + confidence

Corrections NEVER overwrite. Fixing a mistake = reversing entry + new entry.
That gives an audit trail an accountant (or the IRS) can trust.
"""
import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    income = "income"
    expense = "expense"


class EntrySource(str, enum.Enum):
    manual = "manual"
    receipt = "receipt"
    voice = "voice"
    adjustment = "adjustment"
    reversal = "reversal"


class TxnKind(str, enum.Enum):
    money_in = "money_in"
    money_out = "money_out"


class TxnStatus(str, enum.Enum):
    posted = "posted"
    voided = "voided"


class ReceiptStatus(str, enum.Enum):
    needs_review = "needs_review"   # low confidence -> user must confirm
    auto_posted = "auto_posted"     # high confidence -> posted automatically
    posted = "posted"               # user confirmed
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    locale: Mapped[str] = mapped_column(String(8), default="es")       # "en" | "es"
    mode: Mapped[str] = mapped_column(String(16), default="both")      # personal | business | both
    tax_set_aside_pct: Mapped[float] = mapped_column(Float, default=0.25)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")


class Account(Base):
    """Chart of accounts. The user never sees the word 'account' — they see
    plain-language categories. schedule_c_line links a business expense
    category to its line on Form 1040 Schedule C for export."""
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(24))                      # e.g. "1000", "5090"
    name_en: Mapped[str] = mapped_column(String(120))
    name_es: Mapped[str] = mapped_column(String(120))
    type: Mapped[AccountType] = mapped_column(Enum(AccountType))
    is_business: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_c_line: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "8", "24b", ...
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="accounts")


class JournalEntry(Base):
    """Immutable. Rows are only ever inserted, never updated or deleted."""
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[EntrySource] = mapped_column(Enum(EntrySource), default=EntrySource.manual)
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["JournalLine"]] = relationship(back_populates="entry")


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    credit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    entry: Mapped["JournalEntry"] = relationship(back_populates="lines")
    account: Mapped["Account"] = relationship()


class Transaction(Base):
    """The simple thing the user actually sees and edits.
    Every transaction maps to exactly one balanced journal entry."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"))
    kind: Mapped[TxnKind] = mapped_column(Enum(TxnKind))
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    counterparty: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    category_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    is_business: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(24), default="cash")    # cash | card | transfer | check
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id"), nullable=True)
    status: Mapped[TxnStatus] = mapped_column(Enum(TxnStatus), default=TxnStatus.posted)
    voided_by_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    category: Mapped["Account"] = relationship(foreign_keys=[category_account_id])


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(16), default="photo")   # photo | voice
    raw_text: Mapped[str] = mapped_column(Text, default="")
    extracted_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[ReceiptStatus] = mapped_column(Enum(ReceiptStatus), default=ReceiptStatus.needs_review)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
