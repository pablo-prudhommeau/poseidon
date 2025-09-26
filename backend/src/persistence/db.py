from __future__ import annotations
import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _default_sqlite_file() -> Path:
    return _backend_root() / "data" / "poseidon.db"

def _resolve_db_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    db_file = Path(os.getenv("POSEIDON_DB_PATH", _default_sqlite_file()))
    db_file = db_file.expanduser().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    return str(URL.create("sqlite", database=db_file.as_posix()))

DB_URL = _resolve_db_url()
_url = make_url(DB_URL)

connect_args = {}
engine_kwargs = dict(pool_pre_ping=True)

if _url.drivername.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(str(_url), connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if _url.drivername.startswith("sqlite") and (_url.database or "") not in ("", ":memory:"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _):
        try:
            c = dbapi_connection.cursor()
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA synchronous=NORMAL;")
            c.close()
        except Exception:
            pass

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """Crée les tables si absentes."""
    from .models import Base
    Base.metadata.create_all(bind=engine)
