"""Phase A1 — the daily forward feed from data.gov.in, for every crop.

    GET https://api.data.gov.in/resource/{resource_id}
        ?api-key=..&format=json&limit=..&offset=..
        &filters[state]=Maharashtra&filters[commodity]=Onion

Supersedes `ingestion/agmarknet.py`, which does the same thing for exactly one
crop and holds every page in memory until the end. Three differences, and each
one is a lesson we paid for:

  * **Every crop.** The commodity list comes from config/crops.yaml, so adding
    a crop is a config change, not a code change.
  * **Every page hits the disk before it is parsed.** A throttle, a dropped
    connection or a Ctrl-C then costs us nothing we already fetched — re-running
    replays from the cache. We lost a whole afternoon's fetching to a rate limit
    once; that must not be possible twice.
  * **One crop failing is not the run failing.** Tomato returning nothing is
    Tuesday. *Every* crop returning nothing is an outage, and `min_total_rows`
    turns that into a loud failure rather than a quiet success — silence from an
    upstream API looks exactly like a quiet market unless we refuse to accept it.

Nothing here invents a row. A crop with no data produces a WARN and no rows.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import httpx
import pandas as pd

from core import logging as log
from core.config import crop_specs, settings
from core.db import get_conn
from core.errors import IngestionError
from ingestion import RunCounters, normalise_units, upsert_price_observations
from ingestion.cleaners import CANONICAL_COLUMNS, CleaningReport, clean_frame
from ingestion.entity_resolution import Resolver

SOURCE: str = "agmarknet_api"          # same source tag: it is the same upstream data

_CFG = settings.sources.datagov
PAGE_LIMIT: int = int(_CFG.page_limit)
MAX_PAGES: int = int(_CFG.max_pages)
STATE: str = str(_CFG.state)
ATTEMPTS: int = int(_CFG.retry.attempts)
BACKOFF: list[float] = [float(s) for s in _CFG.retry.backoff_seconds]
PAUSE_SECONDS: float = float(_CFG.pause_seconds)
TIMEOUT: float = float(settings.sources.ingestion.http_timeout_seconds)
MIN_TOTAL_ROWS: int = int(_CFG.min_total_rows)
CACHE_DIR: Path = settings.path(*str(_CFG.cache_dir).split("/"))
DATE_FORMAT: str = str(_CFG.date_format)


# ══════════════════════════════════════════════════════════════════════════
# what a run produced
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class CropResult:
    """One crop's slice of a collection run."""

    crop: str
    api_commodity: str
    pages: int = 0
    rows_fetched: int = 0
    rows_matched: int = 0
    rows_written: int = 0
    pages_from_cache: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "crop": self.crop,
            "api_commodity": self.api_commodity,
            "pages": self.pages,
            "rows_fetched": self.rows_fetched,
            "rows_matched": self.rows_matched,
            "rows_written": self.rows_written,
            "pages_from_cache": self.pages_from_cache,
            "error": self.error,
        }


@dataclass
class CollectResult:
    run_date: date
    crops: list[CropResult] = field(default_factory=list)
    report: CleaningReport = field(default_factory=CleaningReport)
    used_keyword_filters: bool = False
    dry_run: bool = False

    @property
    def rows_fetched(self) -> int:
        return sum(c.rows_fetched for c in self.crops)

    @property
    def rows_written(self) -> int:
        return sum(c.rows_written for c in self.crops)

    @property
    def failed_crops(self) -> list[str]:
        return [c.crop for c in self.crops if not c.ok]

    @property
    def empty_crops(self) -> list[str]:
        return [c.crop for c in self.crops if c.ok and c.rows_fetched == 0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "run_date": self.run_date.isoformat(),
            "crops_attempted": len(self.crops),
            "rows_fetched": self.rows_fetched,
            "rows_written": self.rows_written,
            "failed_crops": self.failed_crops,
            "empty_crops": self.empty_crops,
            "used_keyword_filters": self.used_keyword_filters,
            "dry_run": self.dry_run,
            "per_crop": [c.to_dict() for c in self.crops],
            **self.report.to_dict(),
        }


# ══════════════════════════════════════════════════════════════════════════
# which crops, under which upstream name
# ══════════════════════════════════════════════════════════════════════════

def api_commodities(only: Sequence[str] | None = None) -> dict[str, str]:
    """our crop key -> the commodity name data.gov.in filters on.

    Defaults to each crop's first alias in crops.yaml, which is written to be
    the upstream spelling. Overridable in sources.yaml when the two vocabularies
    genuinely disagree — a wrong name here costs us a WARN and zero rows, never
    a wrong row, because the alias table maps the *response* back to an id.
    """
    override = _CFG.get("commodities")
    crops = crop_specs()

    mapping: dict[str, str] = {}
    if override:
        for entry in override:
            if isinstance(entry, str):
                mapping[entry.lower()] = entry
            else:  # a {crop: api_name} pair
                for key, value in dict(entry).items():
                    mapping[str(key).lower()] = str(value)
    else:
        for key, spec in crops.items():
            aliases = list(spec.get("aliases") or [])
            mapping[str(key).lower()] = str(aliases[0]) if aliases else str(key).title()

    if only:
        wanted = {c.strip().lower() for c in only}
        unknown = wanted - set(mapping)
        if unknown:
            raise IngestionError(
                f"unknown crop(s) {sorted(unknown)}. config/crops.yaml has: {sorted(mapping)}"
            )
        mapping = {k: v for k, v in mapping.items() if k in wanted}

    if not mapping:
        raise IngestionError("no crops configured — config/crops.yaml is empty")
    return mapping


# ══════════════════════════════════════════════════════════════════════════
# the page cache — why a throttle costs us nothing
# ══════════════════════════════════════════════════════════════════════════

def cache_dir(run_date: date, crop: str) -> Path:
    return CACHE_DIR / run_date.isoformat() / crop.lower().replace(" ", "_")


def _page_path(run_date: date, crop: str, page: int) -> Path:
    return cache_dir(run_date, crop) / f"page-{page:03d}.json"


def _store_page(run_date: date, crop: str, page: int, records: list[dict[str, Any]]) -> None:
    path = _page_path(run_date, crop, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "crop": crop,
        "page": page,
        "records": records,
    }
    # write-then-rename, so a kill mid-write cannot leave a half-parsed page
    # that a later run would trust.
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _load_page(run_date: date, crop: str, page: int) -> list[dict[str, Any]] | None:
    path = _page_path(run_date, crop, page)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("records") or [])
    except (json.JSONDecodeError, OSError) as exc:
        log.warn("datagov_cache_unreadable", path=str(path), error=str(exc))
        return None


def cached_pages(run_date: date, crop: str) -> list[list[dict[str, Any]]]:
    """Contiguous cached pages from page 0. A hole ends the run of usable pages."""
    pages: list[list[dict[str, Any]]] = []
    index = 0
    while index < MAX_PAGES:
        records = _load_page(run_date, crop, index)
        if records is None:
            break
        pages.append(records)
        index += 1
    return pages


# ══════════════════════════════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════════════════════════════

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
            records: list[dict[str, Any]] = []
            if response.status_code == 200:
                payload = response.json()
                records = list(payload.get("records") or [])
            log.external_call(url, response.status_code, rows=len(records),
                              offset=offset, attempt=attempt + 1)
            if response.status_code == 200:
                return records
            if response.status_code in (401, 403):
                # No amount of backoff fixes a bad key. Fail now, clearly.
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
    raise IngestionError(
        f"datagov: {ATTEMPTS} attempts failed at offset {offset} for {filters}: {last_error}"
    )


def fetch_crop(
    client: httpx.Client,
    crop: str,
    api_commodity: str,
    run_date: date,
    *,
    resume: bool = True,
    filters_extra: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int, int, bool]:
    """Every page for one crop. Returns (records, pages, pages_from_cache, used_keyword).

    Resume is page-level. Cached pages are replayed from disk; fetching picks up
    at the first page we do not have. A cached *short* page means the crop was
    already walked to the end, so we stop without a single request.
    """
    url = _endpoint()
    filters = {"state": STATE, "commodity": api_commodity, **(filters_extra or {})}
    used_keyword = False

    pages: list[list[dict[str, Any]]] = cached_pages(run_date, crop) if resume else []
    from_cache = len(pages)
    if from_cache:
        log.info("datagov_resume", crop=crop, pages_from_cache=from_cache)

    # A cached short page means we already reached the end of this crop.
    if pages and len(pages[-1]) < PAGE_LIMIT:
        return [r for page in pages for r in page], len(pages), from_cache, used_keyword

    index = len(pages)
    while index < MAX_PAGES:
        records = _get_page(client, url, index * PAGE_LIMIT, filters)

        if index == 0 and not records:
            # Newer resources expect filters[state.keyword]=... instead.
            suffix = str(_CFG.filter_key_fallback_suffix)
            retry_filters = {f"{k}{suffix}": v for k, v in filters.items()}
            log.warn("datagov_filter_fallback", crop=crop,
                     tried=list(filters), retry_with=list(retry_filters))
            records = _get_page(client, url, 0, retry_filters)
            if records:
                filters = retry_filters
                used_keyword = True

        _store_page(run_date, crop, index, records)
        pages.append(records)
        index += 1
        if len(records) < PAGE_LIMIT:
            break

    if index >= MAX_PAGES:
        log.warn("datagov_page_cap_hit", crop=crop, pages=index, limit=MAX_PAGES)

    return [r for page in pages for r in page], len(pages), from_cache, used_keyword


# ══════════════════════════════════════════════════════════════════════════
# parsing — shared with ingestion/agmarknet.py, which is the single-crop version
# ══════════════════════════════════════════════════════════════════════════

def records_to_frame(
    records: Iterable[Mapping[str, Any]],
    resolver: Resolver,
    *,
    columns: Mapping[str, str],
    date_format: str,
    units: Mapping[str, str],
) -> pd.DataFrame:
    """API JSON -> the canonical frame `clean_frame()` expects.

    Rows whose mandi or commodity cannot be resolved are dropped here rather
    than guessed at. `Resolver` counts every one of them, so a systematic
    mismatch shows up in the audit as a number instead of as missing data
    nobody noticed.
    """
    mapping = {k: str(v) for k, v in columns.items()}
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return raw

    required = ("obs_date", "mandi", "commodity", "modal_price")
    missing = [col for field_, col in mapping.items()
               if field_ in required and col not in raw.columns]
    if missing:
        raise IngestionError(
            f"data.gov.in response has no field(s) {missing}. Actual fields: "
            f"{list(raw.columns)}. Fix config/sources.yaml -> datagov.api_columns."
        )

    df = raw.rename(columns={col: f for f, col in mapping.items() if col in raw.columns})
    for field_ in CANONICAL_COLUMNS:
        if field_ not in df.columns and field_ != "arrival_qtl":
            df[field_] = None
    df["arrival_qtl"] = df["arrival"] if "arrival" in df.columns else None

    commodity_ids = df["commodity"].map(lambda n: resolver.resolve_commodity(str(n)).entity_id)
    df = df[commodity_ids.notna()].copy()
    if df.empty:
        return df
    df["commodity_id"] = commodity_ids[commodity_ids.notna()].astype(int)

    districts = df["district"] if "district" in df.columns else pd.Series("", index=df.index)
    states = df["state"] if "state" in df.columns else pd.Series("", index=df.index)
    df["mandi_id"] = [
        resolver.resolve_mandi(str(n), str(d or ""), str(s or "")).entity_id
        for n, d, s in zip(df["mandi"], districts, states)
    ]
    df = df[df["mandi_id"].notna()].copy()
    if df.empty:
        return df
    df["mandi_id"] = df["mandi_id"].astype(int)

    df["obs_date"] = pd.to_datetime(df["obs_date"], format=date_format, errors="coerce")
    df = df[df["obs_date"].notna()].copy()
    df = normalise_units(df, units)
    return df[list(CANONICAL_COLUMNS)]


# ══════════════════════════════════════════════════════════════════════════
# the run
# ══════════════════════════════════════════════════════════════════════════

def run(
    counters: RunCounters | None = None,
    *,
    crops: Sequence[str] | None = None,
    run_date: date | None = None,
    resume: bool = True,
    dry_run: bool = False,
) -> CollectResult:
    """Walk every configured crop, writing each one as it lands.

    Idempotent by construction: the UNIQUE key on `price_observations` absorbs
    re-runs, so running this twice in a morning is safe and expected.
    """
    stamp = run_date or date.today()
    wanted = api_commodities(crops)
    result = CollectResult(run_date=stamp, dry_run=dry_run)

    log.info("datagov_start", run_date=stamp.isoformat(), crops=len(wanted),
             resume=resume, dry_run=dry_run)

    columns = _CFG.api_columns.to_dict()
    units = _CFG.units.to_dict()

    with get_conn() as conn, httpx.Client(follow_redirects=True) as client:
        resolver = Resolver(conn)
        for position, (crop, api_name) in enumerate(sorted(wanted.items())):
            crop_result = CropResult(crop=crop, api_commodity=api_name)
            result.crops.append(crop_result)
            try:
                records, pages, from_cache, used_keyword = fetch_crop(
                    client, crop, api_name, stamp, resume=resume
                )
                crop_result.pages = pages
                crop_result.pages_from_cache = from_cache
                crop_result.rows_fetched = len(records)
                result.used_keyword_filters |= used_keyword

                if not records:
                    # Tuesday, not an outage. The run-level check below decides.
                    log.warn("datagov_crop_empty", crop=crop, api_commodity=api_name)
                    continue

                frame = records_to_frame(
                    records, resolver, columns=columns,
                    date_format=DATE_FORMAT, units=units,
                )
                crop_result.rows_matched = int(len(frame))
                if frame.empty:
                    log.warn("datagov_crop_unresolved", crop=crop, fetched=len(records))
                    continue

                cleaned, report = clean_frame(frame)
                result.report.merge(report)
                if not dry_run:
                    crop_result.rows_written = upsert_price_observations(conn, cleaned, SOURCE)
                else:
                    crop_result.rows_written = int(len(cleaned))

                log.info("datagov_crop_done", crop=crop, pages=pages,
                         fetched=crop_result.rows_fetched, matched=crop_result.rows_matched,
                         written=crop_result.rows_written, cached=from_cache)
            except IngestionError as exc:
                # One crop's failure must not cost us the other twelve.
                crop_result.error = f"{type(exc).__name__}: {exc}"[:500]
                log.error("datagov_crop_failed", crop=crop, error=str(exc)[:300])

            if position < len(wanted) - 1 and crop_result.pages > crop_result.pages_from_cache:
                time.sleep(PAUSE_SECONDS)

        resolver.flush_review()

    if counters is not None:
        counters.rows_in = result.rows_fetched
        counters.rows_kept = result.rows_written
        counters.rows_rejected = result.report.rows_rejected
        for crop_result in result.crops:
            counters.add_detail(crop_result.crop, crop_result.rows_written)

    _assert_not_vacuous(result)

    log.info("datagov_done", crops=len(result.crops), fetched=result.rows_fetched,
             written=result.rows_written, failed=result.failed_crops,
             empty=result.empty_crops)
    return result


def _assert_not_vacuous(result: CollectResult) -> None:
    """A run that fetched nothing at all is an outage wearing a success's clothes."""
    if result.rows_fetched >= MIN_TOTAL_ROWS:
        return
    detail = ", ".join(
        f"{c.crop}={c.error or 'empty'}" for c in result.crops
    )
    raise IngestionError(
        f"data.gov.in returned 0 rows across all {len(result.crops)} crops for "
        f"state={STATE} on {result.run_date}. Nothing was written — we do not invent data. "
        f"Check the resource id, the API key, and that the dataset still publishes "
        f"this state. Per crop: {detail}"
    )
