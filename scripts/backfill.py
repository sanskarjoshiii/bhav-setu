"""Phase 2.9 — one command that fills the database with everything.

    python scripts/backfill.py                    # full run
    python scripts/backfill.py --skip-agmarknet   # no data.gov.in key yet
    python scripts/backfill.py --only audit       # just regenerate the report

Order: CSV backfill -> Agmarknet top-up -> weather -> shocks -> routing -> audit.
Idempotent: every step upserts, so re-running is safe and expected.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Any, Callable

import _bootstrap  # noqa: F401  (sys.path side effect)

from core import logging as log
from core.config import settings
from core.errors import BhavSetuError, ConfigError
from ingestion import ingestion_run
from ingestion import agmarknet, audit, backfill_csv, ceda, routing, shocks, weather

# ceda runs first: it is the historical backbone (3 years of daily prices AND
# arrivals). The CSV step is optional now and only adds a source-specific dump.
STEPS: tuple[str, ...] = ("ceda", "csv", "agmarknet", "weather", "shocks", "routing", "audit")


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _run_step(name: str, fn: Callable[..., Any], summary: dict[str, Any], **kwargs: Any) -> bool:
    """Run one step inside an ingestion_runs record. Returns False if it failed."""
    try:
        with ingestion_run(name) as counters:
            result = fn(counters=counters, **kwargs)
        summary[name] = result.to_dict() if hasattr(result, "to_dict") else result
        return True
    except BhavSetuError as exc:
        summary[name] = {"failed": f"{type(exc).__name__}: {exc}"}
        print(f"\n⛔ step '{name}' failed:\n   {exc}\n", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill every Phase 2 data source.")
    for step in STEPS:
        parser.add_argument(f"--skip-{step}", action="store_true", help=f"skip the {step} step")
    parser.add_argument("--only", choices=STEPS, help="run a single step and stop")
    parser.add_argument("--weather-from", type=_parse_date, default=None,
                        help="YYYY-MM-DD; defaults to the first price observation")
    args = parser.parse_args(argv)

    def wanted(step: str) -> bool:
        return args.only == step if args.only else not getattr(args, f"skip_{step}")

    summary: dict[str, Any] = {}
    failures: list[str] = []

    if wanted("ceda"):
        if not _run_step("ceda", ceda.run, summary):
            failures.append("ceda")

    if wanted("csv"):
        if not backfill_csv.CSV_PATH.exists():
            log.info("csv_skipped", reason="no file", path=str(backfill_csv.CSV_PATH))
        elif not _run_step("csv_backfill", backfill_csv.run, summary):
            failures.append("csv")

    if wanted("agmarknet"):
        if not settings.env.data_gov_in_api_key or not settings.env.agmarknet_resource_id:
            print(
                "\n⛔ BLOCKED — human action required:\n"
                "   DATA_GOV_IN_API_KEY / AGMARKNET_RESOURCE_ID are empty in .env.\n"
                "   Get them from https://data.gov.in (My Account -> API Key), or re-run\n"
                "   with --skip-agmarknet to backfill from the CSV only.\n",
                file=sys.stderr,
            )
            return 2
        if not _run_step("agmarknet", agmarknet.run, summary):
            failures.append("agmarknet")

    if wanted("weather"):
        if not _run_step("weather", weather.run, summary, start=args.weather_from):
            failures.append("weather")

    if wanted("shocks"):
        if not _run_step("shocks", shocks.run, summary):
            failures.append("shocks")

    if wanted("routing"):
        if not _run_step("routing", routing.warm_cache, summary):
            failures.append("routing")

    # Per-rule cleaning counts live in an artifact so the audit can report them
    # even when it is re-run on its own.
    for step_name in ("ceda", "csv_backfill"):
        cleaning = summary.get(step_name)
        if isinstance(cleaning, dict) and "rejected_by_rule" in cleaning:
            audit.write_rejections(cleaning)
            break

    if wanted("audit"):
        try:
            report = audit.run()
        except BhavSetuError as exc:
            print(f"\n⛔ audit failed: {exc}\n", file=sys.stderr)
            return 1
        usable = len(report.usable_mandis)
        print(
            f"\n📄 audit report: {audit.REPORT_PATH}\n"
            f"   {usable}/{len(report.mandis)} mandis USABLE, "
            f"{report.shock_events} shock events loaded\n"
        )
        if usable < 3:
            print(
                "⛔ MANUAL STEP: fewer than 3 usable mandis. Open the audit report, pick "
                "denser mandis from your CSV, update config/mandis.yaml, re-run make initdb "
                "and make backfill.",
                file=sys.stderr,
            )
        if report.shock_events < shocks.MIN_EXPECTED_EVENTS:
            print(
                f"⛔ MANUAL STEP: only {report.shock_events} shock events. Fill "
                f"{shocks.CSV_PATH} with ~20 real onion policy events "
                f"(export bans, MEP orders, stock limits) — one line each with a source URL.",
                file=sys.stderr,
            )

    if failures:
        print(f"\n❌ backfill finished with failed step(s): {', '.join(failures)}", file=sys.stderr)
        return 1
    log.info("backfill_complete", steps=list(summary))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as exc:
        print(f"⛔ configuration problem: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
