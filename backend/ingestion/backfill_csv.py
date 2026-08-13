"""Phase 2.1 — load the historical Kaggle mandi CSV into price_observations.

    data/raw/mandi_history.csv  ->  filter  ->  resolve  ->  clean  ->  upsert

Column names come from config/sources.yaml (csv_backfill.columns) because every
Kaggle dump spells them differently. Nothing about the file's shape is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import IngestionError
from ingestion import RunCounters, normalise_units, upsert_price_observations
from ingestion.cleaners import CANONICAL_COLUMNS, CleaningReport, clean_frame
from ingestion.entity_resolution import Resolver

SOURCE: str = "csv_backfill"
_CFG = settings.sources.csv_backfill
CSV_PATH: Path = settings.path(*str(_CFG.path).split("/"))
CHUNK_SIZE: int = int(_CFG.chunk_size)


@dataclass
class BackfillResult:
    rows_read: int = 0
    rows_wrong_commodity: int = 0
    rows_unmatched_mandi: int = 0
    rows_matched: int = 0
    rows_written: int = 0
    report: CleaningReport = field(default_factory=CleaningReport)
    unmatched_mandi_names: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "rows_read": self.rows_read,
            "rows_wrong_commodity": self.rows_wrong_commodity,
            "rows_unmatched_mandi": self.rows_unmatched_mandi,
            "rows_matched": self.rows_matched,
            "rows_written": self.rows_written,
            "unmatched_mandi_names": self.unmatched_mandi_names,
            **self.report.to_dict(),
        }


def _column_map() -> dict[str, str]:
    """canonical field -> CSV header, from config."""
    return {k: str(v) for k, v in _CFG.columns.to_dict().items()}


def _read_chunks(path: Path) -> Iterator[pd.DataFrame]:
    if not path.exists():
        raise IngestionError(
            f"missing {path}.\n"
            f"⛔ MANUAL STEP: download the Kaggle daily mandi price CSV, save it there, "
            f"then check its headers match config/sources.yaml -> csv_backfill.columns"
        )
    yield from pd.read_csv(
        path,
        chunksize=CHUNK_SIZE,
        dtype=str,
        keep_default_na=True,
        encoding="utf-8-sig",
        on_bad_lines="warn",
    )


def _check_headers(df: pd.DataFrame, mapping: dict[str, str]) -> None:
    """Fail on the first chunk, not after twenty minutes of silent zero-matching."""
    required = ("obs_date", "mandi", "commodity", "modal_price")
    missing = [
        mapping[field]
        for field in required
        if mapping.get(field) and mapping[field] not in df.columns
    ]
    if missing:
        raise IngestionError(
            f"{CSV_PATH.name} has no column(s) {missing}. "
            f"Its actual headers are {list(df.columns)}. "
            f"Fix config/sources.yaml -> csv_backfill.columns."
        )


def _parse_dates(raw: pd.Series) -> pd.Series:
    """Configured format first; fall back to day-first inference for odd rows."""
    fmt = str(_CFG.date_format)
    parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
    unparsed = parsed.isna() & raw.notna()
    if unparsed.any():
        parsed.loc[unparsed] = pd.to_datetime(
            raw[unparsed], errors="coerce", dayfirst=True, format="mixed"
        )
    return parsed


def _prepare_chunk(chunk: pd.DataFrame, mapping: dict[str, str], resolver: Resolver,
                   result: BackfillResult) -> pd.DataFrame:
    """Map columns, keep onion rows for our 5 mandis, convert units."""
    present = {field: col for field, col in mapping.items() if col in chunk.columns}
    df = chunk.rename(columns={col: field for field, col in present.items()})
    for field in CANONICAL_COLUMNS:
        if field == "arrival_qtl":
            continue
        if field not in df.columns:
            df[field] = None
    df["arrival_qtl"] = df["arrival"] if "arrival" in df.columns else None

    # commodity first: it discards the great majority of rows cheaply
    commodity_ids = df["commodity"].map(
        lambda name: resolver.resolve_commodity(str(name)).entity_id
    )
    keep = commodity_ids.notna()
    result.rows_wrong_commodity += int((~keep).sum())
    df = df[keep].copy()
    df["commodity_id"] = commodity_ids[keep].astype(int)
    if df.empty:
        return df

    districts = df["district"] if "district" in df.columns else pd.Series("", index=df.index)
    states = df["state"] if "state" in df.columns else pd.Series("", index=df.index)
    mandi_ids = [
        resolver.resolve_mandi(str(name), str(district or ""), str(state or "")).entity_id
        for name, district, state in zip(df["mandi"], districts, states)
    ]
    df["mandi_id"] = pd.Series(mandi_ids, index=df.index)
    matched = df["mandi_id"].notna()
    result.rows_unmatched_mandi += int((~matched).sum())
    df = df[matched].copy()
    if df.empty:
        return df
    df["mandi_id"] = df["mandi_id"].astype(int)

    df["obs_date"] = _parse_dates(df["obs_date"])
    bad_dates = df["obs_date"].isna()
    if bad_dates.any():
        result.report.rejected["reject_unparseable_date"] += int(bad_dates.sum())
        df = df[~bad_dates].copy()

    df = normalise_units(df, _CFG.units.to_dict())
    result.rows_matched += int(len(df))
    return df[list(CANONICAL_COLUMNS)]


def run(counters: RunCounters | None = None) -> BackfillResult:
    """Load the whole CSV. Idempotent — safe to rerun."""
    result = BackfillResult()
    mapping = _column_map()
    log.info("csv_backfill_start", path=str(CSV_PATH), chunk_size=CHUNK_SIZE)

    with get_conn() as conn:
        resolver = Resolver(conn)
        kept: list[pd.DataFrame] = []
        for i, chunk in enumerate(_read_chunks(CSV_PATH)):
            if i == 0:
                _check_headers(chunk, mapping)
            result.rows_read += int(len(chunk))
            prepared = _prepare_chunk(chunk, mapping, resolver, result)
            if not prepared.empty:
                kept.append(prepared)
            log.info(
                "csv_chunk",
                chunk=i,
                rows=int(len(chunk)),
                kept=int(len(prepared)),
                running_total=result.rows_matched,
            )

        if not kept:
            raise IngestionError(
                f"{CSV_PATH.name}: 0 rows matched onion at the 5 configured mandis.\n"
                f"  unmatched mandi names seen: "
                f"{dict(resolver.unmatched_mandis.most_common(10))}\n"
                f"  unmatched commodity names:  "
                f"{dict(resolver.unmatched_commodities.most_common(10))}\n"
                f"Either the CSV covers a different region (update config/mandis.yaml) "
                f"or the column mapping in config/sources.yaml is wrong."
            )

        raw_frame = pd.concat(kept, ignore_index=True)
        cleaned, report = clean_frame(raw_frame)
        result.report = report
        result.rows_written = upsert_price_observations(conn, cleaned, SOURCE)
        resolver.flush_review()
        result.unmatched_mandi_names = dict(resolver.unmatched_mandis.most_common(20))

    if counters is not None:
        counters.rows_in = result.rows_read
        counters.rows_kept = result.rows_written
        counters.rows_rejected = result.report.rows_rejected
        counters.detail.update({k: v for k, v in result.report.rejected.items()})

    log.info(
        "csv_backfill_done",
        rows_read=result.rows_read,
        matched=result.rows_matched,
        written=result.rows_written,
        rejected=result.report.rows_rejected,
        imputed=result.report.imputed,
        suspect=result.report.suspect,
    )
    return result
