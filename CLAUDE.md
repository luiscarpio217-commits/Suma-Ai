# Suma — project instructions for Claude Code

Plain-language money tracking for self-employed immigrant households in the US.
Motto: **complex accounting under the hood, zero accounting vocabulary on the surface.**
The user sees four numbers: Entró / Salió / Te queda / Aparta para impuestos.

Working title "Suma" — trademark/domain check still pending; keep the name in
config/strings so a rename is cheap.

## Architecture

```
backend/   FastAPI + SQLAlchemy 2 + SQLite (dev) / Postgres (prod)
  app/models.py        double-entry ledger + user-facing Transaction layer
  app/seed.py          bilingual chart of accounts w/ Schedule C line mapping
  app/services/ledger.py      THE ENGINE — read this first
  app/services/categorize.py  Claude receipt/voice extraction + confidence gate
  app/services/export.py      Accountant Export (Schedule C CSV, txn listing)
  app/routers/         transactions, capture, dashboard, export, deps (auth)
frontend/  vanilla-JS PWA, no build step, served by FastAPI static mount
  locales/en.json, es.json    ALL user-facing copy lives here — never hardcode
```

## Non-negotiable invariants (do not "refactor" these away)

1. **Every journal entry balances.** `_post_entry` raises `UnbalancedEntry` otherwise.
2. **Journal entries are immutable.** No UPDATE/DELETE on `journal_entries` /
   `journal_lines`, ever. Corrections = reversing entry + new entry
   (`void_transaction`). This is the audit trail.
3. **Cash-basis accounting.** Money is recognized when it moves.
4. **Confidence gate.** AI extractions below `settings.confidence_gate` (0.85)
   go to needs_review. Never silently guess on someone's money.
5. **The AI categorizes and explains; it never gives tax advice.** The system
   prompt in categorize.py forbids opining on deductibility. Keep it that way —
   this is a liability line, not a style choice.
6. **All user-facing strings go through the locale files.** English and Spanish
   ship together; the structure must stay language-agnostic so a third language
   is a new JSON file, not a rebuild.
7. **Plain language on the surface.** No "debit/credit/reconcile/ledger" in any
   UI string. If a string needs an accounting degree, rewrite it.

## Run

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env        # set SUMA_API_KEY; ANTHROPIC_API_KEY optional
uvicorn app.main:app --reload  # serves API + PWA at http://localhost:8000
pytest                          # ledger invariant tests must stay green
```

Without ANTHROPIC_API_KEY the app works fully manually (capture returns
needs_review and the sheet opens pre-filled for the user to confirm).

## Roadmap (build in this order — vertical slice, one path at a time)

### Phase 1 — finish the core slice
- [x] Needs-review queue: list receipts w/ status needs_review, confirm/edit/reject UI
- [x] Edit-as-void-plus-repost flow in the UI (backend already supports it)
- [ ] Receipt photo capture from the PWA (camera input -> /api/capture/photo)
- [ ] Monthly history view (prior months' four numbers)
- [ ] Quarterly tax due-date card (static IRS dates + set-aside running total)

### Phase 2 — real product
- [ ] Multi-user auth (JWT + registration); replace the static X-API-Key +
      first-user shortcut in routers/deps.py. Every query already filters by
      user_id, so this is contained.
- [ ] Postgres migration (SQLAlchemy URL swap + alembic); models are portable
- [ ] Voice notes: client-side recording -> Whisper transcription -> /api/capture/text
- [ ] Stripe subscription (~$15-19/mo target)
- [ ] Mileage log (Schedule C line 9 standard-mileage support)
- [ ] Accountant Export as ZIP: CSVs + receipt images

### Phase 3 — channels
- [ ] WhatsApp capture layer via Business API (capture only, not the product;
      note Meta charges for service replies from Oct 1 2026 — budget ~$0.01-0.015
      per outbound message w/ BSP markup)
- [ ] Tax-preparer referral portal (one preparer = 50-200 clients)

## Deployment target

DigitalOcean droplet already running EDGE2 (FastAPI/systemd). Deploy Suma as a
separate systemd unit behind nginx on its own subdomain. On the $6/1GB tier,
watch memory once Postgres enters; plan the $12 tier.

## Context for decisions

- Audience is often not tech-savvy; every flow must survive "my parents use it."
  Three taps max to log money. Voice and photo beat typing.
- Launch window: US tax season (Jan-Apr) is peak buying intent.
- The Accountant Export is the anti-shoebox feature and the referral hook —
  keep it first-class.
