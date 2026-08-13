"""Phase 2.6 — load hand-curated policy shocks from data/manual/shock_events.csv.

Round 1 does no scraping. A human writes ~20 real onion policy events (export
bans, minimum export price orders, stock limits, buffer releases) with a source
URL each, and this loads them. Phase 3 turns them into decayed features.

Columns: event_date, event_type, commodity, scope, direction, magnitude,
         decay_days, title, source_url
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import text

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import IngestionError
from ingestion import RunCounters
from ingestion.entity_resolution import Resolver

CSV_PATH: Path = settings.path(*str(settings.sources.manual_files.shock_events).split("/"))
REQUIRED_COLUMNS: tuple[str, ...] = (
    "event_date", "event_type", "commodity", "scope",
    "direction", "magnitude", "decay_days", "title", "source_url",
)
VALID_DIRECTIONS: frozenset[int] = frozenset({-1, 1})
VALID_MAGNITUDES: frozenset[int] = frozenset({1, 2, 3})
MIN_EXPECTED_EVENTS: int = 15          # the Phase 2 acceptance bar


@dataclass
class ShockResult:
    rows_read: int = 0
    rows_written: int = 0
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": "manual_csv",
            "rows_read": self.rows_read,
            "rows_written": self.rows_written,
            "problems": self.problems,
        }


def _data_rows(path: Path) -> Iterator[dict[str, str]]:
    """CSV reader that skips '#' comment lines."""
    if not path.exists():
        raise IngestionError(f"missing {path} — Phase 2 manual step 3")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = [line for line in fh if not line.lstrip().startswith("#")]
    if not lines:
        raise IngestionError(f"{path} is empty — it needs at least a header row")
    reader = csv.DictReader(lines)
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise IngestionError(f"{path.name} is missing column(s) {missing}")
    yield from reader


def _parse_int(value: str, field_name: str, allowed: frozenset[int], where: str) -> int:
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise IngestionError(f"{where}: {field_name}='{value}' is not an integer") from exc
    if parsed not in allowed:
        raise IngestionError(
            f"{where}: {field_name}={parsed} is not one of {sorted(allowed)}"
        )
    return parsed


def _parse_date(value: str, where: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise IngestionError(f"{where}: bad event_date '{value}', expected YYYY-MM-DD") from exc


def run(counters: RunCounters | None = None) -> ShockResult:
    """Upsert every event. Idempotent on (event_date, event_type, commodity, scope)."""
    result = ShockResult()
    with get_conn() as conn:
        resolver = Resolver(conn)
        for i, row in enumerate(_data_rows(CSV_PATH), start=2):
            where = f"{CSV_PATH.name} line {i}"
            result.rows_read += 1

            commodity = resolver.resolve_commodity(row["commodity"])
            if not commodity.matched:
                raise IngestionError(
                    f"{where}: commodity '{row['commodity']}' does not match any alias. "
                    f"Add it to config/crops.yaml and re-run init_db."
                )

            decay_days = int(str(row["decay_days"]).strip() or 30)
            if decay_days <= 0:
                raise IngestionError(f"{where}: decay_days must be positive, got {decay_days}")

            conn.execute(
                text(
                    """
                    INSERT INTO shock_events
                        (event_date, event_type, commodity_id, scope, direction,
                         magnitude, source_url, title, decay_days)
                    VALUES (:event_date, :event_type, :commodity_id, :scope, :direction,
                            :magnitude, :source_url, :title, :decay_days)
                    ON CONFLICT (event_date, event_type, commodity_id, scope) DO UPDATE SET
                        direction  = EXCLUDED.direction,
                        magnitude  = EXCLUDED.magnitude,
                        source_url = EXCLUDED.source_url,
                        title      = EXCLUDED.title,
                        decay_days = EXCLUDED.decay_days
                    """
                ),
                {
                    "event_date": _parse_date(row["event_date"], where),
                    "event_type": row["event_type"].strip(),
                    "commodity_id": commodity.entity_id,
                    "scope": (row["scope"] or "national").strip(),
                    "direction": _parse_int(row["direction"], "direction", VALID_DIRECTIONS, where),
                    "magnitude": _parse_int(row["magnitude"], "magnitude", VALID_MAGNITUDES, where),
                    "source_url": (row["source_url"] or "").strip(),
                    "title": (row["title"] or "").strip(),
                    "decay_days": decay_days,
                },
            )
            result.rows_written += 1

    if result.rows_written < MIN_EXPECTED_EVENTS:
        message = (
            f"only {result.rows_written} shock events loaded, Phase 2 expects "
            f"at least {MIN_EXPECTED_EVENTS}. Fill {CSV_PATH} with real onion policy "
            f"events — this is a manual step and it directly improves the model."
        )
        result.problems.append(message)
        log.warn("shocks_below_target", loaded=result.rows_written,
                 expected=MIN_EXPECTED_EVENTS, path=str(CSV_PATH))

    if counters is not None:
        counters.rows_in = result.rows_read
        counters.rows_kept = result.rows_written

    log.info("shocks_done", read=result.rows_read, written=result.rows_written)
    return result
