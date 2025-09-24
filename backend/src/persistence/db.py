# backend/src/persistence/db.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Emplacement de la BDD: backend/data/poseidon.db (par défaut)
BACKEND_DIR = Path(__file__).resolve().parents[2]           # .../backend
DB_PATH = os.getenv("POSEIDON_DB_PATH") or str(BACKEND_DIR / "data" / "poseidon.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# SQLite + FastAPI (threading) => check_same_thread=False
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Iterator[Session]:
    """Dépendance FastAPI: ouvre une session et la ferme proprement."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """Crée les tables si absentes."""
    # Base est définie dans models.py
    from .models import Base  # import local pour éviter cycles
    Base.metadata.create_all(bind=engine)

__all__ = ["engine", "SessionLocal", "get_db", "init_db", "DATABASE_URL"]
