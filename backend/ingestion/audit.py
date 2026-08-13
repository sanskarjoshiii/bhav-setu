"""Phase 2.8 — the honest data quality report.

Writes data/artifacts/data_audit.md and prints a rich table. When a judge asks
"how good is your data?", you open this file instead of guessing.

Verdict per mandi (thresholds in config/sources.yaml -> audit):
    USABLE   enough rows AND enough business-day coverage to train on
    THIN     usable only as a neighbour signal; do not headline it
    UNUSABLE swap it out in config/mandis.yaml and re-run the backfill
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from core import logging as log
from core.config import settings
from core.db import get_conn

_CFG = settings.sources.audit
REPORT_PATH: Path = settings.path(*str(_CFG.report_path).split("/"))
REJECTIONS_PATH: Path = settings.path(*str(_CFG.rejections_path).split("/"))
USABLE_MIN_ROWS: int = int(_CFG.usable.min_rows)
USABLE_MIN_COVERAGE: float = float(_CFG.usable.min_coverage)
THIN_MIN_ROWS: int = int(_CFG.thin.min_rows)
THIN_MIN_COVERAGE: float = float(_CFG.thin.min_coverage)

VERDICT_STYLE: dict[str, str] = {"USABLE": "green", "THIN": "yellow", "UNUSABLE": "red"}


@dataclass
class MandiAudit:
    mandi_id: int
    mandi: str
    rows: int
    first_date: date | None
    last_date: date | None
    business_days: int
    coverage: float
    imputed_pct: float
    suspect_pct: float
    longest_gap_days: int
    price_min: float | None
    price_median: float | None
    price_max: float | None
    arrival_min: float | None
    arrival_median: float | None
    arrival_max: float | None
    weather_rows: int
    verdict: str


@dataclass
class AuditReport:
    generated_at: datetime
    mandis: list[MandiAudit] = field(default_factory=list)
    shock_events: int = 0
    rejections: dict[str, Any] = field(default_factory=dict)

    @property
    def usable_mandis(self) -> list[MandiAudit]:
        return [m for m in self.mandis if m.verdict == "USABLE"]


def _verdict(rows: int, coverage: float) -> str:
    if rows >= USABLE_MIN_ROWS and coverage >= USABLE_MIN_COVERAGE:
        return "USABLE"
    if rows >= THIN_MIN_ROWS and coverage >= THIN_MIN_COVERAGE:
        return "THIN"
    return "UNUSABLE"


def _longest_gap(dates: pd.Series) -> int:
    """Longest run of consecutive missing business days inside the covered range."""
    if len(dates) < 2:
        return 0
    observed = pd.DatetimeIndex(sorted(pd.to_datetime(dates.unique())))
    calendar = pd.bdate_range(observed.min(), observed.max())
    missing = ~calendar.isin(observed)
    if not missing.any():
        return 0
    longest = current = 0
    for is_missing in missing:
        current = current + 1 if is_missing else 0
        longest = max(longest, current)
    return int(longest)


def _load_rejections() -> dict[str, Any]:
    if not REJECTIONS_PATH.exists():
        return {}
    try:
        return json.loads(REJECTIONS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warn("rejections_unreadable", path=str(REJECTIONS_PATH), error=str(exc))
        return {}


def write_rejections(payload: dict[str, Any]) -> Path:
    """Called by scripts/backfill.py so per-rule counts survive into the report."""
    REJECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    REJECTIONS_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return REJECTIONS_PATH


def collect() -> AuditReport:
    """Read the database and compute every statistic the report shows."""
    report = AuditReport(generated_at=datetime.now(), rejections=_load_rejections())

    with get_conn() as conn:
        mandis = [dict(r) for r in conn.execute(
            text("SELECT id, name FROM mandis WHERE active ORDER BY name")
        ).mappings()]
        prices = pd.DataFrame(
            [dict(r) for r in conn.execute(
                text(
                    "SELECT mandi_id, obs_date, modal_price, arrival_qtl, is_imputed, suspect "
                    "FROM price_observations"
                )
            ).mappings()]
        )
        weather = pd.DataFrame(
            [dict(r) for r in conn.execute(
                text("SELECT mandi_id, count(*) AS n FROM weather_daily GROUP BY mandi_id")
            ).mappings()]
        )
        report.shock_events = int(
            conn.execute(text("SELECT count(*) FROM shock_events")).scalar() or 0
        )

    weather_by_mandi = (
        dict(zip(weather["mandi_id"], weather["n"])) if not weather.empty else {}
    )

    for mandi in mandis:
        subset = (
            prices[prices["mandi_id"] == mandi["id"]]
            if not prices.empty
            else pd.DataFrame(columns=["obs_date", "modal_price", "arrival_qtl",
                                       "is_imputed", "suspect"])
        )
        rows = int(len(subset))
        if rows:
            obs_dates = pd.to_datetime(subset["obs_date"])
            first, last = obs_dates.min().date(), obs_dates.max().date()
            business_days = int(len(pd.bdate_range(first, last)))
            coverage = rows / business_days if business_days else 0.0
            modal = pd.to_numeric(subset["modal_price"], errors="coerce")
            arrivals = pd.to_numeric(subset["arrival_qtl"], errors="coerce").dropna()
            audit = MandiAudit(
                mandi_id=int(mandi["id"]),
                mandi=str(mandi["name"]),
                rows=rows,
                first_date=first,
                last_date=last,
                business_days=business_days,
                coverage=round(min(coverage, 1.0), 4),
                imputed_pct=round(100.0 * float(subset["is_imputed"].mean()), 2),
                suspect_pct=round(100.0 * float(subset["suspect"].mean()), 2),
                longest_gap_days=_longest_gap(subset["obs_date"]),
                price_min=_num(modal.min()),
                price_median=_num(modal.median()),
                price_max=_num(modal.max()),
                arrival_min=_num(arrivals.min()) if len(arrivals) else None,
                arrival_median=_num(arrivals.median()) if len(arrivals) else None,
                arrival_max=_num(arrivals.max()) if len(arrivals) else None,
                weather_rows=int(weather_by_mandi.get(mandi["id"], 0)),
                verdict=_verdict(rows, min(coverage, 1.0)),
            )
        else:
            audit = MandiAudit(
                mandi_id=int(mandi["id"]), mandi=str(mandi["name"]), rows=0,
                first_date=None, last_date=None, business_days=0, coverage=0.0,
                imputed_pct=0.0, suspect_pct=0.0, longest_gap_days=0,
                price_min=None, price_median=None, price_max=None,
                arrival_min=None, arrival_median=None, arrival_max=None,
                weather_rows=int(weather_by_mandi.get(mandi["id"], 0)),
                verdict="UNUSABLE",
            )
        report.mandis.append(audit)

    return report


def print_table(report: AuditReport, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(title="Data audit — onion, per mandi", header_style="bold")
    for column in ("Mandi", "Rows", "From", "To", "Cover", "Imputed", "Suspect",
                   "Max gap", "Price min/med/max", "Arrivals med", "Weather", "Verdict"):
        table.add_column(column, justify="right" if column != "Mandi" else "left")

    for m in report.mandis:
        table.add_row(
            m.mandi,
            f"{m.rows:,}",
            str(m.first_date or "—"),
            str(m.last_date or "—"),
            f"{m.coverage:.0%}",
            f"{m.imputed_pct:.1f}%",
            f"{m.suspect_pct:.1f}%",
            str(m.longest_gap_days),
            "—" if m.price_median is None
            else f"{m.price_min:,.0f} / {m.price_median:,.0f} / {m.price_max:,.0f}",
            "—" if m.arrival_median is None else f"{m.arrival_median:,.0f}",
            f"{m.weather_rows:,}",
            f"[{VERDICT_STYLE[m.verdict]}]{m.verdict}[/]",
        )
    console.print(table)

    rejected = report.rejections.get("rejected_by_rule") or {}
    if rejected:
        rules = Table(title="Rows rejected, by rule", header_style="bold")
        rules.add_column("Rule")
        rules.add_column("Rows", justify="right")
        for rule, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
            rules.add_row(rule, f"{count:,}")
        console.print(rules)

    console.print(
        f"shock events loaded: {report.shock_events}   "
        f"usable mandis: {len(report.usable_mandis)}/{len(report.mandis)}"
    )


def _markdown(report: AuditReport) -> str:
    lines: list[str] = [
        "# Data audit — Bhav Setu Round 1",
        "",
        f"Generated {report.generated_at:%Y-%m-%d %H:%M}. "
        "Every number here comes from the database, not from a spreadsheet.",
        "",
        "One canonical daily series per (mandi, commodity): source rows differing only "
        "by variety or grade are merged with an arrival-weighted modal price. "
        "Grade is applied later as a price factor (Phase 5), not as a separate series.",
        "",
        "## Verdicts",
        "",
        f"- **USABLE** — ≥ {USABLE_MIN_ROWS:,} rows and ≥ {USABLE_MIN_COVERAGE:.0%} "
        "of business days covered. Train on it.",
        f"- **THIN** — ≥ {THIN_MIN_ROWS:,} rows and ≥ {THIN_MIN_COVERAGE:.0%} coverage. "
        "Keep as a neighbour signal only.",
        "- **UNUSABLE** — swap the mandi in `config/mandis.yaml` and re-run `make backfill`.",
        "",
        "## Per mandi",
        "",
        "| Mandi | Rows | From | To | Business-day coverage | Imputed | Suspect | "
        "Longest gap (days) | Modal ₹/qtl min / median / max | Arrivals qtl min / median / max | "
        "Weather rows | Verdict |",
        "|---|---:|---|---|---:|---:|---:|---:|---|---|---:|---|",
    ]
    for m in report.mandis:
        price = ("—" if m.price_median is None
                 else f"{m.price_min:,.0f} / {m.price_median:,.0f} / {m.price_max:,.0f}")
        arrivals = ("—" if m.arrival_median is None
                    else f"{m.arrival_min:,.0f} / {m.arrival_median:,.0f} / {m.arrival_max:,.0f}")
        lines.append(
            f"| {m.mandi} | {m.rows:,} | {m.first_date or '—'} | {m.last_date or '—'} | "
            f"{m.coverage:.1%} | {m.imputed_pct:.1f}% | {m.suspect_pct:.1f}% | "
            f"{m.longest_gap_days} | {price} | {arrivals} | {m.weather_rows:,} | "
            f"**{m.verdict}** |"
        )

    lines += ["", "## Cleaning", ""]
    rejections = report.rejections
    if rejections:
        lines += [
            f"- rows read: **{rejections.get('rows_in', 0):,}**",
            f"- rows written: **{rejections.get('rows_kept', 0):,}**",
            f"- rows imputed (gap ≤ 3 business days, forward-filled, `is_imputed=true`): "
            f"**{rejections.get('imputed', 0):,}**",
            f"- rows flagged suspect (kept, not deleted): **{rejections.get('suspect', 0):,}**",
            "",
            "| Rule | Rows rejected |",
            "|---|---:|",
        ]
        by_rule = rejections.get("rejected_by_rule") or {}
        for rule, count in sorted(by_rule.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{rule}` | {count:,} |")
        if not by_rule:
            lines.append("| — | 0 |")
        unmatched = rejections.get("unmatched_mandi_names") or {}
        if unmatched:
            lines += [
                "",
                "### Source mandi names we could not resolve",
                "",
                "| Raw name | Rows |", "|---|---:|",
            ]
            lines += [f"| {name} | {count:,} |" for name, count in unmatched.items()]
    else:
        lines.append(
            f"_No cleaning stats found at `{REJECTIONS_PATH.relative_to(settings.root)}` — "
            "run `make backfill` to regenerate them._"
        )

    lines += [
        "",
        "## Other sources",
        "",
        f"- shock events loaded: **{report.shock_events}**",
        f"- mandis with weather: **{sum(1 for m in report.mandis if m.weather_rows > 0)}"
        f"/{len(report.mandis)}**",
        "",
        "## Verdict",
        "",
        f"**{len(report.usable_mandis)} of {len(report.mandis)} mandis are USABLE.** "
        + ("Phase 2 target met (≥ 3 usable)."
           if len(report.usable_mandis) >= 3
           else "⛔ Below the Phase 2 target of 3 — replace the weak mandis in "
                "`config/mandis.yaml` and re-run `make backfill`."),
        "",
    ]
    return "\n".join(lines)


def write_report(report: AuditReport | None = None) -> Path:
    report = report or collect()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_markdown(report), encoding="utf-8")
    log.info("audit_written", path=str(REPORT_PATH), mandis=len(report.mandis),
             usable=len(report.usable_mandis))
    return REPORT_PATH


def run() -> AuditReport:
    """Collect, print and write. The Phase 2 deliverable."""
    report = collect()
    print_table(report)
    write_report(report)
    return report


def _num(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def to_dict(report: AuditReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "shock_events": report.shock_events,
        "mandis": [asdict(m) for m in report.mandis],
    }


if __name__ == "__main__":
    run()
