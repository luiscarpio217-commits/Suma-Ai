"""Needs-review queue — the human half of the confidence gate.
Everything the AI wasn't sure enough about lands here for the user to
confirm, edit, or reject. Thin wrappers; the logic lives in services/review."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Receipt, User
from ..schemas import ReviewConfirm, ReviewDraft, ReviewItemOut, TxnOut
from ..services import review as review_svc
from .deps import current_user, require_key

router = APIRouter(prefix="/api/review", dependencies=[Depends(require_key)])


def _item(receipt: Receipt) -> ReviewItemOut:
    return ReviewItemOut(
        receipt_id=receipt.id,
        source=receipt.source,
        created_at=receipt.created_at,
        confidence=receipt.confidence,
        has_image=Path(receipt.file_path).is_file(),
        draft=ReviewDraft(**review_svc.receipt_draft(receipt)),
    )


@router.get("", response_model=list[ReviewItemOut])
def list_pending(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [_item(r) for r in review_svc.pending_receipts(db, user)]


@router.post("/{receipt_id}/confirm", response_model=TxnOut)
def confirm(receipt_id: int, body: ReviewConfirm, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    try:
        return review_svc.confirm_receipt(
            db, user, receipt_id, amount=body.amount, txn_date=body.txn_date,
            category_account_id=body.category_account_id,
            counterparty=body.counterparty, is_business=body.is_business,
            method=body.method,
        )
    except review_svc.ReviewNotFound:
        raise HTTPException(status_code=404, detail="receipt not found")
    except review_svc.AlreadyHandled:
        raise HTTPException(status_code=409, detail="receipt already handled")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{receipt_id}/reject")
def reject(receipt_id: int, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    try:
        review_svc.reject_receipt(db, user, receipt_id)
    except review_svc.ReviewNotFound:
        raise HTTPException(status_code=404, detail="receipt not found")
    except review_svc.AlreadyHandled:
        raise HTTPException(status_code=409, detail="receipt already handled")
    return {"ok": True}


@router.get("/{receipt_id}/image")
def receipt_image(receipt_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    receipt = db.get(Receipt, receipt_id)
    if receipt is None or receipt.user_id != user.id:
        raise HTTPException(status_code=404, detail="receipt not found")
    path = Path(receipt.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not available")
    return FileResponse(path)
