import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (Account, EntrySource, Receipt, ReceiptStatus, TxnKind, User)
from ..schemas import ExtractionOut, TextCapture
from ..services import categorize, ledger
from .deps import current_user, require_key

router = APIRouter(prefix="/api/capture", dependencies=[Depends(require_key)])


def _maybe_post(db, user, receipt, extraction) -> ExtractionOut:
    """Confidence gate: auto-post only when the model is sure AND the
    category resolves. Otherwise the entry waits for the user."""
    auto = False
    txn_id = None
    category = (db.query(Account)
                  .filter_by(user_id=user.id, code=extraction["category_code"])
                  .first())
    if (extraction["ok"] and category is not None
            and extraction["confidence"] >= settings.confidence_gate
            and extraction["amount"] > 0):
        txn = ledger.record_transaction(
            db, user, kind=TxnKind.money_out,
            txn_date=date.fromisoformat(extraction["date"]) if extraction["date"] else date.today(),
            amount=Decimal(str(extraction["amount"])),
            category_account_id=category.id,
            counterparty=extraction["merchant"],
            is_business=extraction["is_business"],
            source=EntrySource.receipt if receipt else EntrySource.voice,
            receipt=receipt,
        )
        auto, txn_id = True, txn.id
        if receipt:
            receipt.status = ReceiptStatus.auto_posted
    elif receipt:
        receipt.status = ReceiptStatus.needs_review
    db.commit()
    return ExtractionOut(
        receipt_id=receipt.id if receipt else None,
        merchant=extraction["merchant"], amount=extraction["amount"],
        date=extraction["date"], category_code=extraction["category_code"],
        is_business=extraction["is_business"], confidence=extraction["confidence"],
        note=extraction["note"], auto_posted=auto, transaction_id=txn_id,
    )


@router.post("/photo", response_model=ExtractionOut)
async def capture_photo(file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    ext = Path(file.filename or "r.jpg").suffix or ".jpg"
    dest = Path(settings.upload_dir) / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(await file.read())

    receipt = Receipt(user_id=user.id, file_path=str(dest), source="photo")
    db.add(receipt)
    db.flush()

    accounts = db.query(Account).filter_by(user_id=user.id).all()
    extraction = categorize.extract_from_receipt(str(dest), accounts, user.locale)
    receipt.raw_text = ""
    receipt.extracted_json = json.dumps(extraction)
    receipt.confidence = extraction["confidence"]
    return _maybe_post(db, user, receipt, extraction)


@router.post("/text", response_model=ExtractionOut)
def capture_text(body: TextCapture, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """Voice notes arrive here after client-side/Whisper transcription,
    e.g. 'gasté 40 en gasolina'. Also works for a typed sentence."""
    accounts = db.query(Account).filter_by(user_id=user.id).all()
    extraction = categorize.extract_from_text(body.text, accounts, body.locale)
    return _maybe_post(db, user, None, extraction)
