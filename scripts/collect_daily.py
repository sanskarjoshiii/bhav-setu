"""Phase A1 — the daily collector. Point cron at this and forget about it.

    python scripts/collect_daily.py --once            # one pass, every crop
    python scripts/collect_daily.py --crops onion tomato
    python scripts/collect_daily.py --dry-run         # fetch and parse, write nothing
    python scripts/collect_daily.py --fresh           # ignore the page cache

Every pass writes one row to `ingestion_runs`, so "did it run last night?" is a
SQL question, not a guess about a log file.

This is the tap that fills the tank for the rest of the project. It is worth
starting on day one and leaving running: by the time the model needs a training
set, this will quietly have collected weeks of it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

import _bootstrap  # noqa: F401  (sys.path side effect)

from core import logging as log
from core.config import settings
from core.errors import BhavSetuError, ConfigError
from ingestion import ingestion_run
from ingestion import datagov

JOB: str = "collect_daily"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _require_credentials() -> str | None:
    """Return a human-readable blocker, or None if we are good to go."""
    missing = [
        name
        for name, value in (
            ("DATA_GOV_IN_API_KEY", settings.env.data_gov_in_api_key),
            ("AGMARKNET_RESOURCE_ID", settings.env.agmarknet_resource_id),
        )
        if not value
    ]
    if not missing:
        return None
    return (
        f"{' and '.join(missing)} {'are' if len(missing) > 1 else 'is'} empty in .env.\n"
        "   Get them from https://data.gov.in — My Account -> API Key, and the resource\n"
        "   UUID of 'Current Daily Price of Various Commodities'. Registration and email\n"
        "   verification take about a day, so do this first."
    )


def _print_summary(result: datagov.CollectResult) -> None:
    rows = sorted(result.crops, key=lambda c: -c.rows_written)
    width = max((len(c.crop) for c in rows), default=4)
    print(f"\n  {'crop'.ljust(width)}  fetched  matched  written  pages  cached")
    print(f"  {'─' * width}  ───────  ───────  ───────  ─────  ──────")
    for crop in rows:
        marker = " ⛔" if crop.error else ("  ·" if crop.rows_fetched == 0 else "")
        print(
            f"  {crop.crop.ljust(width)}  {crop.rows_fetched:>7}  {crop.rows_matched:>7}  "
            f"{crop.rows_written:>7}  {crop.pages:>5}  {crop.pages_from_cache:>6}{marker}"
        )
    print(
        f"\n  {result.rows_fetched} rows fetched, {result.rows_written} written"
        f"{' (dry run — nothing stored)' if result.dry_run else ''}"
    )
    if result.empty_crops:
        print(f"  · no data today: {', '.join(result.empty_crops)}")
    if result.failed_crops:
        print(f"  ⛔ failed: {', '.join(result.failed_crops)}", file=sys.stderr)
    if result.used_keyword_filters:
        print("  ⚠ the resource needed filters[x.keyword] — update sources.yaml if this persists")
    print(f"\n  page cache: {datagov.CACHE_DIR / result.run_date.isoformat()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect today's mandi prices from data.gov.in.",
    )
    parser.add_argument("--once", action="store_true",
                        help="run a single pass and exit (the default; kept for cron clarity)")
    parser.add_argument("--crops", nargs="+", metavar="CROP",
                        help="only these crops (default: every crop in config/crops.yaml)")
    parser.add_argument("--date", type=_parse_date, default=None, metavar="YYYY-MM-DD",
                        help="label the page cache with this date (default: today)")
    parser.add_argument("--fresh", action="store_true",
                        help="ignore cached pages and re-fetch from the API")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch, parse and clean, but write nothing to the database")
    args = parser.parse_args(argv)

    blocker = _require_credentials()
    if blocker:
        print(f"\n⛔ BLOCKED — human action required:\n   {blocker}\n", file=sys.stderr)
        return 2

    try:
        with ingestion_run(JOB) as counters:
            result = datagov.run(
                counters,
                crops=args.crops,
                run_date=args.date,
                resume=not args.fresh,
                dry_run=args.dry_run,
            )
    except BhavSetuError as exc:
        print(f"\n⛔ {type(exc).__name__}: {exc}\n", file=sys.stderr)
        return 1

    _print_summary(result)
    log.info("collect_daily_complete", written=result.rows_written,
             failed=len(result.failed_crops))
    return 1 if result.failed_crops else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as exc:
        print(f"⛔ configuration problem: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
