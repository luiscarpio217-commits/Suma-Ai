"""Suma API — plain-language money tracking for self-employed households.
Run:  uvicorn app.main:app --reload  (from backend/)"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .routers import capture, dashboard, export, review, transactions
from .seed import seed

app = FastAPI(title="Suma", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(capture.router)
app.include_router(review.router)
app.include_router(dashboard.router)
app.include_router(export.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve the PWA if the frontend folder is present (single-droplet deployment)
frontend = Path(__file__).resolve().parents[2] / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
