from datetime import date
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


class DashboardOut(BaseModel):
    year: int
    month: int
    money_in: float
    money_out: float
    net: float
    business_profit: float
    tax_set_aside: float
