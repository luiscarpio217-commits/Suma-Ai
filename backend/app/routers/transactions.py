from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Transaction, User
from ..schemas import CategoryOut, TxnCreate, TxnOut
from ..services import ledger
from .deps import current_user, require_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_key)])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return (db.query(Account)
              .filter(Account.user_id == user.id, Account.active.is_(True),
                      Account.type.in_(["income", "expense"]))
              .order_by(Account.code).all())


@router.get("/transactions", response_model=list[TxnOut])
def list_transactions(limit: int = 50, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    return (db.query(Transaction)
              .filter(Transaction.user_id == user.id)
              .order_by(Transaction.txn_date.desc(), Transaction.id.desc())
              .limit(limit).all())


@router.post("/transactions", response_model=TxnOut)
def create_transaction(body: TxnCreate, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    return ledger.record_transaction(
        db, user, kind=body.kind, txn_date=body.txn_date,
        amount=Decimal(body.amount), category_account_id=body.category_account_id,
        counterparty=body.counterparty, is_business=body.is_business,
        method=body.method, memo=body.memo,
    )


@router.post("/transactions/{txn_id}/void", response_model=TxnOut)
def void_transaction(txn_id: int, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    return ledger.void_transaction(db, user, txn_id)
