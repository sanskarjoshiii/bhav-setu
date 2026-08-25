"""Phase 2.2 — top up recent prices from the data.gov.in Agmarknet resource.

    GET https://api.data.gov.in/resource/{resource_id}
        ?api-key=..&format=json&limit=..&offset=..
        &filters[state]=Maharashtra&filters[commodity]=Onion

Paginates until a short page comes back, retries with exponential backoff, and
logs every call as one line (rule 11). The API mostly serves recent data — the
Kaggle CSV is what we actually train on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

import httpx
import pandas as pd

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import IngestionError
from ingestion import RunCounters, upsert_price_observations
from ingestion import datagov
from ingestion.cleaners import CleaningReport, clean_frame
from ingestion.entity_resolution import Resolver

SOURCE: str = "agmarknet_api"
_CFG = settings.sources.agmarknet
PAGE_LIMIT: int = int(_CFG.page_limit)
MAX_PAGES: int = int(_CFG.max_pages)
ATTEMPTS: int = int(_CFG.retry.attempts)
BACKOFF: list[float] = [float(s) for s in _CFG.retry.backoff_seconds]
TIMEOUT: float = float(settings.sources.ingestion.http_timeout_seconds)


@dataclass
class ApiResult:
    rows_fetched: int = 0
    pages: int = 0
    rows_matched: int = 0
    rows_written: int = 0
    used_keyword_filters: bool = False
    report: CleaningReport = field(default_factory=CleaningReport)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "rows_fetched": self.rows_fetched,
            "pages": self.pages,
            "rows_matched": self.rows_matched,
            "rows_written": self.rows_written,
            "used_keyword_filters": self.used_keyword_filters,
            **self.report.to_dict(),
        }


def _endpoint() -> str:
    resource_id = settings.env.require("agmarknet_resource_id")
    return f"{str(_CFG.base_url).rstrip('/')}/{resource_id}"


def _params(offset: int, filters: Mapping[str, str]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "api-key": settings.env.require("data_gov_in_api_key"),
        "format": "json",
        "limit": PAGE_LIMIT,
        "offset": offset,
    }
    for key, value in filters.items():
        params[f"filters[{key}]"] = value
    return params


def _get_page(client: httpx.Client, url: str, offset: int,
              filters: Mapping[str, str]) -> list[dict[str, Any]]:
    """One page, with exponential backoff. Raises IngestionError once retries run out."""
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            response = client.get(url, params=_params(offset, filters), timeout=TIMEOUT)
            records = []
            if response.status_code == 200:
                payload = response.json()
                records = list(payload.get("records") or [])
            log.external_call(
                url, response.status_code, rows=len(records), offset=offset, attempt=attempt + 1
            )
            if response.status_code == 200:
                return records
            if response.status_code in (401, 403):
                raise IngestionError(
                    f"data.gov.in rejected the API key (HTTP {response.status_code}). "
                    f"Check DATA_GOV_IN_API_KEY in .env."
                )
            last_error = IngestionError(f"HTTP {response.status_code}: {response.text[:200]}")
        except httpx.HTTPError as exc:
            log.external_call(url, "network_error", rows=None, offset=offset,
                              attempt=attempt + 1, error=str(exc))
            last_error = exc
        if attempt < ATTEMPTS - 1:
            time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    raise IngestionError(f"agmarknet: {ATTEMPTS} attempts failed at offset {offset}: {last_error}")


def fetch_records() -> tuple[list[dict[str, Any]], int, bool]:
    """All records for the configured filters. Returns (records, pages, used_keyword)."""
    url = _endpoint()
    filters = {str(k): str(v) for k, v in _CFG.filters.to_dict().items()}
    used_keyword = False

    with httpx.Client(follow_redirects=True) as client:
        first = _get_page(client, url, 0, filters)
        if not first:
            # Newer resources expect filters[state.keyword]=... instead.
            suffix = str(_CFG.filter_key_fallback_suffix)
            retry_filters = {f"{k}{suffix}": v for k, v in filters.items()}
            log.warn("agmarknet_filter_fallback", tried=list(filters), retry_with=list(retry_filters))
            first = _get_page(client, url, 0, retry_filters)
            if first:
                filters = retry_filters
                used_keyword = True

        records = list(first)
        pages = 1
        while len(first) == PAGE_LIMIT and pages < MAX_PAGES:
            first = _get_page(client, url, pages * PAGE_LIMIT, filters)
            records.extend(first)
            pages += 1

    if pages >= MAX_PAGES:
        log.warn("agmarknet_page_cap_hit", pages=pages, limit=MAX_PAGES)
    return records, pages, used_keyword


def _to_frame(records: list[dict[str, Any]], resolver: Resolver,
              result: ApiResult) -> pd.DataFrame:
    """Delegates to the shared parser in ingestion/datagov.py.

    This module is the single-crop version of the same fetch; Phase A1 kept one
    copy of the parsing so a fix to the column mapping cannot reach one caller
    and miss the other. Only the config block differs.
    """
    frame = datagov.records_to_frame(
        records,
        resolver,
        columns=_CFG.api_columns.to_dict(),
        date_format=str(_CFG.date_format),
        units=_CFG.units.to_dict(),
    )
    result.rows_matched = int(len(frame))
    return frame


def run(counters: RunCounters | None = None) -> ApiResult:
    """Fetch, clean and upsert. Idempotent — the UNIQUE key absorbs re-runs."""
    result = ApiResult()
    records, pages, used_keyword = fetch_records()
    result.rows_fetched = len(records)
    result.pages = pages
    result.used_keyword_filters = used_keyword

    if not records:
        raise IngestionError(
            "data.gov.in returned 0 records for "
            f"{_CFG.filters.to_dict()}. Nothing was written — we do not invent data. "
            "Check the resource id and that the dataset still publishes this state/commodity."
        )

    with get_conn() as conn:
        resolver = Resolver(conn)
        frame = _to_frame(records, resolver, result)
        cleaned, report = clean_frame(frame)
        result.report = report
        result.rows_written = upsert_price_observations(conn, cleaned, SOURCE)
        resolver.flush_review()

    if counters is not None:
        counters.rows_in = result.rows_fetched
        counters.rows_kept = result.rows_written
        counters.rows_rejected = result.report.rows_rejected

    log.info(
        "agmarknet_done",
        fetched=result.rows_fetched,
        pages=result.pages,
        matched=result.rows_matched,
        written=result.rows_written,
    )
    return result
