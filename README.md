# Suma — Su dinero, simplemente sumado.

Plain-language money tracking for self-employed households. Rigorous
double-entry accounting under the hood; four numbers on the surface:
**Entró · Salió · Le queda · Guarde para impuestos.**

Bilingual (EN/ES) from day one. AI receipt & voice capture with a confidence
gate — it never silently guesses on your money. One-click Schedule C export
your tax preparer can actually use.

## Quick start

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
# open http://localhost:8000  — API docs at /docs
pytest  # 7 ledger-invariant tests
```

`ANTHROPIC_API_KEY` is optional — without it, capture falls back to a
pre-filled manual review sheet.

## Stack

FastAPI · SQLAlchemy 2 · SQLite→Postgres · vanilla-JS PWA (no build step) ·
Claude (Sonnet) for extraction.

See **CLAUDE.md** for architecture, invariants, and the roadmap.
