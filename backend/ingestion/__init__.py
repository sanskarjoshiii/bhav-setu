"""Phase 2 — data ingestion, cleaning and audit.

Shared plumbing every source needs: run bookkeeping, unit normalisation, and the
one upsert statement that writes `price_observations`.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import IngestionError

UPSERT_BATCH_SIZE: int = int(settings.sources.ingestion.upsert_batch_size)

# Multipliers into our canonical units: ₹/quintal and quintals.
PRICE_UNIT_FACTOR: dict[str, float] = {
    "rupees_per_quintal": 1.0,
    "rupees_per_kg": 100.0,
}
ARRIVAL_UNIT_FACTOR: dict[str, float] = {
    "quintal": 1.0,
    "tonne": 10.0,
    "kg": 0.01,
}


@dataclass
class RunCounters:
    """Mutable tally the job fills in while it works."""

    rows_in: int = 0
    rows_kept: int = 0
    rows_rejected: int = 0
    detail: dict[str, int] = field(default_factory=dict)

    def add_detail(self, key: str, n: int = 1) -> None:
        self.detail[key] = self.detail.get(key, 0) + n


@contextmanager
def ingestion_run(job: str) -> Iterator[RunCounters]:
    """Record one row in `ingestion_runs`, whatever happens.

    Re-raises on failure (rule 10: errors are loud) after marking the run failed.
    """
    counters = RunCounters()
    started = datetime.now(timezone.utc)
    log.info("ingestion_start", job=job)
    status = "ok"
    error: str | None = None
    try:
        yield counters
    except Exception as exc:                      # noqa: BLE001 — re-raised below
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        if status == "ok" and counters.rows_rejected and not counters.rows_kept:
            status = "failed"
        elif status == "ok" and counters.rows_rejected:
            status = "partial"
        with get_conn() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_runs
                        (job, started_at, ended_at, status, rows_in, rows_kept, rows_rejected, error)
                    VALUES (:job, :started, :ended, :status, :rows_in, :rows_kept, :rows_rejected, :error)
                    """
                ),
                {
                    "job": job,
                    "started": started,
                    "ended": datetime.now(timezone.utc),
                    "status": status,
                    "rows_in": counters.rows_in,
                    "rows_kept": counters.rows_kept,
                    "rows_rejected": counters.rows_rejected,
                    "error": error,
                },
            )
        log.info(
            "ingestion_end",
            job=job,
            status=status,
            rows_in=counters.rows_in,
            rows_kept=counters.rows_kept,
            rows_rejected=counters.rows_rejected,
            seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        )


def normalise_units(df: pd.DataFrame, units: Mapping[str, str]) -> pd.DataFrame:
    """Convert source units to ₹/quintal and quintals, recording what we did.

    Raises rather than guessing: an unrecognised unit means the config is wrong,
    and silently treating tonnes as quintals would corrupt every arrivals feature.
    """
    price_unit = str(units["price"])
    arrival_unit = str(units["arrival"])
    try:
        price_factor = PRICE_UNIT_FACTOR[price_unit]
        arrival_factor = ARRIVAL_UNIT_FACTOR[arrival_unit]
    except KeyError as exc:
        raise IngestionError(
            f"unknown unit {exc} in config/sources.yaml. "
            f"price must be one of {sorted(PRICE_UNIT_FACTOR)}, "
            f"arrival one of {sorted(ARRIVAL_UNIT_FACTOR)}"
        ) from exc

    out = df.copy()
    for column in ("min_price", "max_price", "modal_price"):
        out[column] = pd.to_numeric(out[column], errors="coerce") * price_factor
    out["arrival_qtl"] = pd.to_numeric(out["arrival_qtl"], errors="coerce") * arrival_factor
    if price_factor != 1.0 or arrival_factor != 1.0:
        log.info(
            "units_normalised",
            price_unit=price_unit,
            price_factor=price_factor,
            arrival_unit=arrival_unit,
            arrival_factor=arrival_factor,
        )
    return out


_UPSERT_SQL = text(
    """
    INSERT INTO price_observations
        (obs_date, mandi_id, commodity_id, variety, grade,
         min_price, max_price, modal_price, arrival_qtl,
         source, is_imputed, suspect, raw)
    VALUES
        (:obs_date, :mandi_id, :commodity_id, :variety, :grade,
         :min_price, :max_price, :modal_price, :arrival_qtl,
         :source, :is_imputed, :suspect, CAST(:raw AS jsonb))
    ON CONFLICT (obs_date, mandi_id, commodity_id, variety, grade) DO UPDATE SET
        min_price   = EXCLUDED.min_price,
        max_price   = EXCLUDED.max_price,
        modal_price = EXCLUDED.modal_price,
        arrival_qtl = EXCLUDED.arrival_qtl,
        source      = EXCLUDED.source,
        is_imputed  = EXCLUDED.is_imputed,
        suspect     = EXCLUDED.suspect,
        raw         = EXCLUDED.raw,
        ingested_at = now()
    -- an imputed row must never overwrite a real observation
    WHERE price_observations.is_imputed OR NOT EXCLUDED.is_imputed
    """
)


def upsert_price_observations(conn: Connection, df: pd.DataFrame, source: str) -> int:
    """Idempotent write. Returns the number of rows sent.

    Re-running a backfill is expected and must not duplicate or degrade anything,
    which is what the UNIQUE key plus the is_imputed guard above buy us.
    """
    if df.empty:
        return 0

    records: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        raw = row.get("raw")
        records.append(
            {
                "obs_date": _as_date(row["obs_date"]),
                "mandi_id": int(row["mandi_id"]),
                "commodity_id": int(row["commodity_id"]),
                "variety": str(row.get("variety") or ""),
                "grade": str(row.get("grade") or ""),
                "min_price": _as_float(row.get("min_price")),
                "max_price": _as_float(row.get("max_price")),
                "modal_price": _as_float(row["modal_price"]),
                "arrival_qtl": _as_float(row.get("arrival_qtl")),
                "source": source,
                "is_imputed": bool(row.get("is_imputed", False)),
                "suspect": bool(row.get("suspect", False)),
                "raw": json.dumps(raw, default=str) if isinstance(raw, (dict, list)) else None,
            }
        )

    for start in range(0, len(records), UPSERT_BATCH_SIZE):
        conn.execute(_UPSERT_SQL, records[start : start + UPSERT_BATCH_SIZE])
    return len(records)


def _as_date(value: Any) -> Any:
    ts = pd.Timestamp(value)
    return ts.date()


def _as_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return float(value)
