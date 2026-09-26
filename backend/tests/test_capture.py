"""Receipt photos from the PWA: what the server accepts, where it lands, and
the confidence gate (invariant #4) end to end — a sure read posts itself, an
unsure one waits for the user, and nothing is ever guessed silently."""
import struct
import zlib
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.config import settings
from app.models import JournalLine, Receipt, ReceiptStatus, Transaction
from app.routers import capture as capture_router
from app.services import categorize


def png_bytes(size=8):
    rows = b"".join(b"\x00" + b"\xf0\xa2\x27" * size for _ in range(size))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture()
def uploads(monkeypatch, tmp_path):
    """No real AI calls (even if a developer's .env has a key) and a throwaway
    upload folder."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


def send(client, data, name="receipt.jpg"):
    return client.post("/api/capture/photo", files={"file": (name, data, "image/jpeg")})


def ledger_balances(db):
    debit = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    return Decimal(debit) == Decimal(credit)


def test_photo_without_ai_waits_for_review(client, db, uploads):
    r = send(client, png_bytes(), "IMG_2231.png")
    assert r.status_code == 200
    body = r.json()
    assert body["auto_posted"] is False and body["transaction_id"] is None

    receipt = db.get(Receipt, body["receipt_id"])
    assert receipt.status == ReceiptStatus.needs_review
    assert [p.suffix for p in uploads.iterdir()] == [".png"]

    queue = client.get("/api/review").json()
    assert [(i["receipt_id"], i["has_image"]) for i in queue] == [(receipt.id, True)]
    image = client.get(f"/api/review/{receipt.id}/image")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")


def test_saved_extension_comes_from_the_bytes_not_the_name(client, uploads):
    assert send(client, png_bytes(), "receipt.html").status_code == 200
    assert send(client, JPEG, "photo").status_code == 200
    assert sorted(p.suffix for p in uploads.iterdir()) == [".jpg", ".png"]


@pytest.mark.parametrize("data", [
    b"<html><script>alert(1)</script></html>",
    b"GIF89a" + b"\x00" * 32,      # a real image, but not one we accept
    b"",
])
def test_anything_but_a_jpeg_or_png_is_refused(client, db, uploads, data):
    assert send(client, data).status_code == 415
    assert db.query(Receipt).count() == 0
    assert list(uploads.iterdir()) == []


def test_oversized_photo_is_refused(client, db, uploads, monkeypatch):
    monkeypatch.setattr(capture_router, "MAX_PHOTO_BYTES", 100)
    assert send(client, png_bytes(size=64)).status_code == 413
    assert db.query(Receipt).count() == 0
    assert list(uploads.iterdir()) == []


@pytest.mark.parametrize("confidence, code, posts_itself", [
    (0.97, "5022", True),
    (0.85, "5022", True),     # the gate is ">=": exactly 0.85 is sure enough
    (0.849, "5022", False),
    (0.97, "9999", False),    # sure, but of a category that doesn't exist
])
def test_confidence_gate(client, db, uploads, monkeypatch, confidence, code, posts_itself):
    monkeypatch.setattr(categorize, "extract_from_receipt", lambda *a, **k: {
        "merchant": "Home Depot", "amount": 84.5, "date": "2026-07-20",
        "category_code": code, "is_business": True, "confidence": confidence,
        "note": "Materiales de trabajo.", "ok": True})
    body = send(client, JPEG).json()
    receipt = db.get(Receipt, body["receipt_id"])

    assert body["auto_posted"] is posts_itself
    assert body["merchant"] == "Home Depot" and body["amount"] == 84.5
    if posts_itself:
        txn = db.get(Transaction, body["transaction_id"])
        assert txn.receipt_id == receipt.id and Decimal(txn.amount) == Decimal("84.50")
        assert receipt.status == ReceiptStatus.auto_posted
    else:
        assert db.query(Transaction).count() == 0
        assert receipt.status == ReceiptStatus.needs_review
    assert ledger_balances(db)
