from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .models import TxnKind


class CategoryOut(BaseModel):
    id: int
    code: str
    name_en: str
    name_es: str
    type: str
    is_business: bool
    schedule_c_line: str | None

    class Config:
        from_attributes = True


class TxnCreate(BaseModel):
    kind: TxnKind
    txn_date: date
    amount: Decimal = Field(gt=0)
    category_account_id: int
    counterparty: str = ""
    is_business: bool = False
    method: str = "cash"
    memo: str = ""


class TxnOut(BaseModel):
    id: int
    kind: TxnKind
    txn_date: date
    amount: Decimal
    counterparty: str
    category_account_id: int
    is_business: bool
    method: str
    status: str
    receipt_id: int | None

    class Config:
        from_attributes = True


class TextCapture(BaseModel):
    text: str
    locale: str = "es"


class ExtractionOut(BaseModel):
    receipt_id: int | None = None
    merchant: str
    amount: float
    date: str | None
    category_code: str
    is_business: bool
    confidence: float
    note: str
    auto_posted: bool
    transaction_id: int | None = None


class ReviewDraft(BaseModel):
    """What the AI thinks the receipt says — editable, never auto-posted."""
    merchant: str = ""
    amount: float = 0.0
    date: str | None = None
    category_code: str = ""
    is_business: bool = False
    note: str = ""


class ReviewItemOut(BaseModel):
    receipt_id: int
    source: str
    created_at: datetime
    confidence: float
    has_image: bool
    draft: ReviewDraft


class ReviewConfirm(BaseModel):
    """Final values the user confirmed. Receipts post as money out."""
    amount: Decimal = Field(gt=0)
    txn_date: date
    category_account_id: int
    counterparty: str = ""
    is_business: bool = False
    method: str = "cash"


class DashboardOut(BaseModel):
    year: int
    month: int
    money_in: float
    money_out: float
    net: float
    business_profit: float
    tax_set_aside: float
