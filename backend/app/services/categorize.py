"""
AI capture service.

Takes a receipt photo (or transcribed voice note) and asks Claude to extract:
merchant, amount, date, suggested category, business-vs-personal, confidence.

Guardrails:
- Confidence gate: >= settings.confidence_gate auto-posts; below that it goes
  to "needs review" and the user confirms. We never silently guess on money.
- The model categorizes and explains. It NEVER gives tax advice. The system
  prompt forbids opining on deductibility beyond mapping to a category.

If ANTHROPIC_API_KEY is unset, extraction returns needs_review with an empty
draft — the app still works fully manually.
"""
import base64
import json
import mimetypes
from pathlib import Path

import httpx

from ..config import settings

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

SYSTEM = """You extract bookkeeping data from receipts and short voice-note transcriptions
for self-employed people in the US. Respond ONLY with JSON, no prose, no markdown fences:
{"merchant": str, "amount": float, "date": "YYYY-MM-DD" or null,
 "category_code": str, "is_business": bool, "confidence": float 0-1,
 "note": str}
category_code must be one of the provided codes. Pick is_business from context
(a hardware store for a landscaper is business; a supermarket is usually personal).
Set confidence honestly — below 0.85 means a human should review.
"note" is one plain-language sentence in the user's locale explaining your category choice.
You categorize; you never give tax advice or opine on whether something is deductible."""


def _category_menu(accounts) -> str:
    return "\n".join(
        f"{a.code}: {a.name_en} / {a.name_es} ({'business' if a.is_business else 'personal'})"
        for a in accounts if a.type.value == "expense"
    )


def extract_from_receipt(file_path: str, accounts, locale: str = "es") -> dict:
    """Returns dict with keys of SYSTEM's JSON schema plus 'ok': bool."""
    empty = {"merchant": "", "amount": 0.0, "date": None, "category_code": "",
             "is_business": False, "confidence": 0.0, "note": "", "ok": False}
    if not settings.anthropic_api_key:
        return empty

    path = Path(file_path)
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()

    body = {
        "model": MODEL,
        "max_tokens": 500,
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                {"type": "text", "text": f"User locale: {locale}\nAllowed category codes:\n{_category_menu(accounts)}"},
            ],
        }],
    }
    try:
        r = httpx.post(
            ANTHROPIC_URL,
            headers={"x-api-key": settings.anthropic_api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body, timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        parsed = json.loads(text.replace("```json", "").replace("```", "").strip())
        parsed["ok"] = True
        return {**empty, **parsed}
    except Exception:
        return empty


def extract_from_text(transcript: str, accounts, locale: str = "es") -> dict:
    """Same extraction for a voice-note transcript or typed sentence,
    e.g. 'gasté cuarenta en gasolina para la camioneta'."""
    empty = {"merchant": "", "amount": 0.0, "date": None, "category_code": "",
             "is_business": False, "confidence": 0.0, "note": "", "ok": False}
    if not settings.anthropic_api_key:
        return empty
    body = {
        "model": MODEL,
        "max_tokens": 500,
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": f"User locale: {locale}\nAllowed category codes:\n{_category_menu(accounts)}\n\nTranscript: {transcript}",
        }],
    }
    try:
        r = httpx.post(
            ANTHROPIC_URL,
            headers={"x-api-key": settings.anthropic_api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body, timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        parsed = json.loads(text.replace("```json", "").replace("```", "").strip())
        parsed["ok"] = True
        return {**empty, **parsed}
    except Exception:
        return empty
