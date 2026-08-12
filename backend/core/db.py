"""SQLAlchemy 2.0 Core, sync engine. No ORM — everything goes through text()."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from core.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """Process-wide engine, created lazily so importing this module never opens a socket."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.env.database_url,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


@contextmanager
def get_conn() -> Iterator[Connection]:
    """Transactional connection. Commits on success, rolls back on exception."""
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Convenience read helper for scripts and tests."""
    with get_conn() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
    return [dict(row) for row in rows]


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row is not None else None


def ping() -> bool:
    """True if the database answers. Used by check-phase0."""
    with get_conn() as conn:
        return conn.execute(text("SELECT 1")).scalar_one() == 1
