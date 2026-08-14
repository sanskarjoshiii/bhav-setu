"""Phase 2 — CEDA Agri Market Data: 3 years of daily onion prices AND arrivals.

    /api/prices      -> t, cmdty, district_id, district, p_min, p_max, p_modal
    /api/quantities  -> t, cmdty, district_id, district, qty

Both are POST JSON with {state_id, commodity_id, district_id, calculation_type,
start_date, end_date}. They are merged on (obs_date, district) so each row carries
both price and arrivals, then handed to the same cleaners and upsert every other
source uses.

Two hard-won facts about this API, both encoded in config/sources.yaml → ceda:
  * spans longer than ~1 year return 504 from their nginx, so we chunk by year;
  * district_id must be set — omit it and you get a state-wide average instead
    of per-district rows.

Granularity is district-level. See the note at the top of config/mandis.yaml.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import text

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import IngestionError
from ingestion import RunCounters, normalise_units, upsert_price_observations
from ingestion.cleaners import CANONICAL_COLUMNS, CleaningReport, clean_frame

SOURCE: str = "ceda_api"
_CFG = settings.sources.ceda

BASE_URL: str = str(_CFG.base_url)
PRICES_URL: str = BASE_URL + str(_CFG.prices_path)
QUANTITIES_URL: str = BASE_URL + str(_CFG.quantities_path)
TIMEOUT: float = float(_CFG.http_timeout_seconds)
PAUSE: float = float(_CFG.pause_seconds)
CHUNK_MONTHS: int = int(_CFG.chunk_months)
ATTEMPTS: int = int(_CFG.retry.attempts)
BACKOFF: list[float] = [float(s) for s in _CFG.retry.backoff_seconds]
CACHE_DIR: Path = settings.path(*str(_CFG.cache_dir).split("/"))


@dataclass
class CedaResult:
    districts: int = 0
    requests: int = 0
    price_rows: int = 0
    quantity_rows: int = 0
    merged_rows: int = 0
    rows_written: int = 0
    missing_arrivals: int = 0
    per_district: dict[str, int] = field(default_factory=dict)
    report: CleaningReport = field(default_factory=CleaningReport)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "districts": self.districts,
            "requests": self.requests,
            "price_rows": self.price_rows,
            "quantity_rows": self.quantity_rows,
            "merged_rows": self.merged_rows,
            "rows_written": self.rows_written,
            "missing_arrivals": self.missing_arrivals,
            "per_district": self.per_district,
            **self.report.to_dict(),
        }


def _end_date() -> date:
    configured = _CFG.get("end_date")
    return date.today() if configured is None else datetime.strptime(str(configured), "%Y-%m-%d").date()


def _chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Year-sized windows. Ends overlap by a day; the UNIQUE key dedupes them."""
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        # timedelta has no months; 12 chunk_months == 365 days is close enough
        stop = min(cursor + timedelta(days=int(CHUNK_MONTHS * 30.4)), end)
        out.append((cursor, stop))
        cursor = stop
    return out


def _cache_path(url: str, payload: dict[str, Any]) -> Path:
    """One file per (endpoint, district, window). Makes the pull resumable."""
    endpoint = url.rsplit("/", 1)[-1]
    name = (f"{endpoint}_{payload['district_id']}_"
            f"{payload['start_date']}_{payload['end_date']}.json")
    return CACHE_DIR / name


def _post(client: httpx.Client, url: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """POST with retries, backed by an on-disk cache.

    CEDA is a public server behind a 60s gateway timeout and it throttles under
    load, so a full pull will not survive one uninterrupted run. Every successful
    window is cached, and a re-run picks up exactly where the last one stopped
    instead of asking them for the same rows again.
    """
    cached = _cache_path(url, payload)
    if cached.exists():
        rows = json.loads(cached.read_text(encoding="utf-8"))
        log.info("ceda_cache_hit", district=payload["district_id"],
                 window=f"{payload['start_date']}..{payload['end_date']}", rows=len(rows))
        return rows

    last_error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = client.post(url, json=payload, timeout=TIMEOUT)
            rows = response.json().get("data", []) if response.is_success else []
            log.external_call(url, response.status_code, rows=len(rows),
                              district=payload.get("district_id"),
                              window=f"{payload['start_date']}..{payload['end_date']}",
                              attempt=attempt)
            if response.is_success:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(rows), encoding="utf-8")
                return rows
            last_error = f"HTTP {response.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log.warn("ceda_request_failed", url=url, attempt=attempt, error=last_error)
        if attempt < ATTEMPTS:
            time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
    raise IngestionError(
        f"CEDA {url} failed after {ATTEMPTS} attempts "
        f"(district={payload.get('district_id')}, "
        f"{payload['start_date']}..{payload['end_date']}): {last_error}"
    )


def _payload(district_id: int, start: date, end: date) -> dict[str, Any]:
    return {
        "state_id": str(_CFG.state_id),
        "commodity_id": str(_CFG.commodity_id),
        "district_id": str(district_id),
        "calculation_type": str(_CFG.calculation_type),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def fetch_district(client: httpx.Client, district_id: int, start: date, end: date,
                   result: CedaResult) -> pd.DataFrame:
    """Prices left-joined with arrivals for one district over the whole span."""
    prices: list[dict[str, Any]] = []
    quantities: list[dict[str, Any]] = []
    for window_start, window_end in _chunks(start, end):
        payload = _payload(district_id, window_start, window_end)
        prices.extend(_post(client, PRICES_URL, payload))
        time.sleep(PAUSE)
        quantities.extend(_post(client, QUANTITIES_URL, payload))
        time.sleep(PAUSE)
        result.requests += 2

    result.price_rows += len(prices)
    result.quantity_rows += len(quantities)
    if not prices:
        return pd.DataFrame()

    price_df = pd.DataFrame(prices).drop_duplicates(subset=["t"], keep="last")
    frame = price_df[["t", "p_min", "p_max", "p_modal"]].copy()

    if quantities:
        qty_df = pd.DataFrame(quantities).drop_duplicates(subset=["t"], keep="last")
        frame = frame.merge(qty_df[["t", "qty"]], on="t", how="left")
    else:
        frame["qty"] = pd.NA

    return frame


def _to_canonical(frame: pd.DataFrame, mandi_id: int, commodity_id: int) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(frame["t"], format=str(_CFG.date_format)).dt.date,
            "mandi_id": mandi_id,
            "commodity_id": commodity_id,
            "variety": "",
            "grade": "",
            "min_price": pd.to_numeric(frame["p_min"], errors="coerce"),
            "max_price": pd.to_numeric(frame["p_max"], errors="coerce"),
            "modal_price": pd.to_numeric(frame["p_modal"], errors="coerce"),
            "arrival_qtl": pd.to_numeric(frame["qty"], errors="coerce"),
        }
    )
    return out[list(CANONICAL_COLUMNS)]


def run(counters: RunCounters | None = None) -> CedaResult:
    """Pull every configured district, clean, and upsert. Idempotent."""
    result = CedaResult()
    counters = counters or RunCounters()

    start = datetime.strptime(str(_CFG.start_date), "%Y-%m-%d").date()
    end = _end_date()

    with get_conn() as conn:
        commodity_id = conn.execute(
            text("SELECT id FROM commodities WHERE lower(name) = 'onion'")
        ).scalar_one()
        mandi_rows = {
            row["name"]: row["id"]
            for row in conn.execute(text("SELECT id, name FROM mandis")).mappings()
        }

    configured = settings.mandis.mandis
    with httpx.Client(headers={"Content-type": "application/json"}) as client:
        for entry in configured:
            spec = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
            name = spec["name"]
            district_id = spec.get("ceda_district_id")
            if district_id is None:
                raise IngestionError(
                    f"mandi '{name}' has no ceda_district_id in config/mandis.yaml"
                )
            mandi_id = mandi_rows.get(name)
            if mandi_id is None:
                raise IngestionError(
                    f"mandi '{name}' is in config/mandis.yaml but not in the database. "
                    f"Run: python scripts/init_db.py --force"
                )

            frame = fetch_district(client, int(district_id), start, end, result)
            result.districts += 1
            if frame.empty:
                log.warn("ceda_no_rows", mandi=name, district_id=district_id)
                result.per_district[name] = 0
                continue

            canonical = _to_canonical(frame, mandi_id, commodity_id)
            canonical = normalise_units(canonical, _CFG.units.to_dict())
            result.missing_arrivals += int(canonical["arrival_qtl"].isna().sum())
            result.merged_rows += len(canonical)

            cleaned, report = clean_frame(canonical)
            result.report.merge(report)

            with get_conn() as conn:
                written = upsert_price_observations(conn, cleaned, SOURCE)
            result.rows_written += written
            result.per_district[name] = written
            log.info("ceda_district_done", mandi=name, district_id=district_id,
                     fetched=len(canonical), written=written)

    counters.rows_in = result.merged_rows
    counters.rows_kept = result.rows_written
    counters.rows_rejected = max(0, result.merged_rows - result.rows_written)
    return result
