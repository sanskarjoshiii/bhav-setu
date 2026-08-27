"""Phase B1 gate — measure the distance between the data we have and a model.

    python scripts/check_data_readiness.py --csv        # no database needed
    python scripts/check_data_readiness.py              # against Postgres
    python scripts/check_data_readiness.py --csv --verbose

Why this exists as its own script. "We need more data" is not actionable; "onion
at Lasalgaon yields 0 trainable rows because its 47 observations are spread over
70 distinct dates in two years, and you need 60 inside any 400-day window" is.
Every threshold below is read from config rather than typed here, so this script
cannot drift away from what `build_features()` will actually accept.

It answers three questions, in order:

  1. How many rows would `build_training_matrix()` emit today?
  2. Which series are carrying the set, and which are dead weight?
  3. How many more days of collection stand between us and the 20,000-row gate?

The simulation is exact, not an estimate: for every candidate as-of date it
applies the same two rules the builder applies — enough real observations in the
lookback, and a settleable label at each horizon.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

import _bootstrap  # noqa: F401  (sys.path side effect)

import numpy as np
import pandas as pd

from core.config import crop_specs, settings

# ── the thresholds that decide everything, all read from config ─────────────
LOOKBACK_DAYS: int = int(settings.app.history_lookback_days)
MIN_OBSERVATIONS: int = int(settings.app.features.min_observations)
HORIZONS: list[int] = [int(h) for h in settings.app.horizons]
LABEL_TOLERANCE_DAYS: int = int(settings.model.dataset.label_tolerance_days)
N_FOLDS: int = int(settings.model.validation.n_folds)
FOLD_MONTHS: int = int(settings.model.validation.fold_months)

#: The Phase B1 gate from PLAN-NOMODEL.md. A matrix below this trains a model
#: that cannot be defended.
TARGET_ROWS: int = 20_000

#: Days of history a series needs before it can contribute anything at all:
#: feature warm-up + the validation structure + the longest label + a purge gap.
VALIDATION_DAYS: int = N_FOLDS * FOLD_MONTHS * 30
WARMUP_DAYS: int = 90
MIN_SERIES_SPAN_DAYS: int = WARMUP_DAYS + 180 + VALIDATION_DAYS + max(HORIZONS) * 2

#: Duration guidance by crop group — see MODEL.md for the reasoning. Seasonal
#: fruits fruit once a year AND trade for only part of it, so calendar years buy
#: far fewer rows than they do for a vegetable.
YEAR_RULE: dict[str, tuple[float, float]] = {   # group -> (floor years, target years)
    "vegetable": (2.0, 3.0),
    "spice": (2.0, 3.0),
    "fruit": (3.0, 4.0),
}
#: Fruits that trade year-round behave like vegetables regardless of their group.
YEAR_ROUND_FRUITS: frozenset[str] = frozenset({"banana"})


@dataclass
class SeriesReport:
    """One (crop, mandi) series, measured against what the builder demands."""

    crop: str
    crop_group: str
    district: str
    mandi: str
    rows: int
    first: date
    last: date
    distinct_dates: int
    longest_gap_days: int
    feature_rows: int          # as-of dates that clear the 60-in-400 gate
    training_rows: int         # those dates x horizons that also settle a label

    @property
    def span_days(self) -> int:
        return (self.last - self.first).days

    @property
    def density(self) -> float:
        """Observations per calendar day. 1.0 would be every single day."""
        return self.distinct_dates / max(self.span_days, 1)

    @property
    def verdict(self) -> str:
        if self.training_rows >= 1_000:
            return "STRONG"
        if self.training_rows > 0:
            return "THIN"
        if self.distinct_dates >= MIN_OBSERVATIONS:
            return "TOO SPARSE"
        return "DEAD"

    def to_dict(self) -> dict[str, Any]:
        return {
            "crop": self.crop, "mandi": self.mandi, "district": self.district,
            "rows": self.rows, "distinct_dates": self.distinct_dates,
            "span_days": self.span_days, "feature_rows": self.feature_rows,
            "training_rows": self.training_rows, "verdict": self.verdict,
        }


# ══════════════════════════════════════════════════════════════════════════
# loading — CSV or Postgres, same shape out
# ══════════════════════════════════════════════════════════════════════════

def _collapse(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per (crop, mandi, day). Varieties and grades merge, as in cleaning."""
    frame = frame.dropna(subset=["obs_date", "modal_price"])
    frame = frame[pd.to_numeric(frame["modal_price"], errors="coerce") > 0]
    return (
        frame.groupby(["commodity", "district", "mandi", "obs_date"], as_index=False)
        .agg(modal_price=("modal_price", "mean"))
    )


def load_from_csv(path: str | None = None) -> pd.DataFrame:
    csv_path = settings.path(*str(
        path or settings.sources.csv_backfill.path
    ).split("/"))
    if not csv_path.exists():
        raise SystemExit(f"⛔ no CSV at {csv_path}")
    frame = pd.read_csv(csv_path, parse_dates=["obs_date"])
    missing = {"obs_date", "district", "mandi", "commodity", "modal_price"} - set(frame.columns)
    if missing:
        raise SystemExit(f"⛔ {csv_path} is missing column(s): {sorted(missing)}")
    return _collapse(frame)


def load_from_db() -> pd.DataFrame:
    """The canonical path. Only real observations — imputed rows cannot be labels."""
    from sqlalchemy import text

    from core.db import get_conn

    sql = text(
        """
        SELECT c.name AS commodity, m.district, m.name AS mandi,
               p.obs_date, p.modal_price
        FROM price_observations p
        JOIN commodities c ON c.id = p.commodity_id
        JOIN mandis      m ON m.id = p.mandi_id
        WHERE p.modal_price IS NOT NULL AND NOT p.is_imputed
        """
    )
    with get_conn() as conn:
        frame = pd.DataFrame(
            [dict(r) for r in conn.execute(sql).mappings()]
        )
    if frame.empty:
        return frame
    frame["obs_date"] = pd.to_datetime(frame["obs_date"])
    return _collapse(frame)


# ══════════════════════════════════════════════════════════════════════════
# the simulation — exactly the builder's two rules, applied to dates alone
# ══════════════════════════════════════════════════════════════════════════

def simulate_series(dates: np.ndarray) -> tuple[int, int]:
    """(feature_rows, training_rows) this series would contribute.

    Rule 1, from `build_features`: an as-of date is usable only if at least
    MIN_OBSERVATIONS real observations fall inside the preceding LOOKBACK_DAYS.

    Rule 2, from `dataset._price_at`: a horizon contributes a row only if some
    real observation lands in [as_of + h - tolerance, as_of + h].

    Both are evaluated on the observation dates themselves, which is what the
    builder does — it never invents an as-of date with no price on it.
    """
    if len(dates) < MIN_OBSERVATIONS:
        return 0, 0

    days = dates.astype("datetime64[D]").astype(np.int64)
    days.sort()

    # Rule 1 — a sliding count over the lookback window.
    window_start = np.searchsorted(days, days - LOOKBACK_DAYS, side="left")
    in_window = np.arange(len(days)) - window_start + 1
    usable = in_window >= MIN_OBSERVATIONS
    feature_rows = int(usable.sum())
    if feature_rows == 0:
        return 0, 0

    # Rule 2 — for each usable as-of and each horizon, is there a settleable label?
    training_rows = 0
    as_of = days[usable]
    for horizon in HORIZONS:
        target = as_of + horizon
        # most recent observation at or before the target date
        position = np.searchsorted(days, target, side="right") - 1
        found = np.where(position >= 0, days[np.clip(position, 0, len(days) - 1)], -10**9)
        training_rows += int(((target - found) <= LABEL_TOLERANCE_DAYS).sum())
    return feature_rows, training_rows


def _group_of(crop: str, specs: dict[str, dict[str, Any]]) -> str:
    key = crop.strip().lower().replace(" ", "_")
    spec = specs.get(key, {})
    return str(spec.get("crop_group", "unknown"))


def measure(frame: pd.DataFrame) -> list[SeriesReport]:
    specs = crop_specs()
    reports: list[SeriesReport] = []
    for (crop, district, mandi), group in frame.groupby(
        ["commodity", "district", "mandi"], sort=True
    ):
        dates = np.sort(group["obs_date"].unique())
        stamps = pd.DatetimeIndex(dates)
        gaps = np.diff(stamps.asi8 // 86_400_000_000_000) if len(dates) > 1 else np.array([0])
        feature_rows, training_rows = simulate_series(dates)
        reports.append(
            SeriesReport(
                crop=str(crop),
                crop_group=_group_of(str(crop), specs),
                district=str(district),
                mandi=str(mandi),
                rows=int(len(group)),
                first=stamps.min().date(),
                last=stamps.max().date(),
                distinct_dates=int(len(dates)),
                longest_gap_days=int(gaps.max()) if len(gaps) else 0,
                feature_rows=feature_rows,
                training_rows=training_rows,
            )
        )
    return sorted(reports, key=lambda r: (-r.training_rows, r.crop, r.mandi))


# ══════════════════════════════════════════════════════════════════════════
# reporting
# ══════════════════════════════════════════════════════════════════════════

def _rule_for(report: SeriesReport) -> tuple[float, float]:
    if report.crop.strip().lower() in YEAR_ROUND_FRUITS:
        return YEAR_RULE["vegetable"]
    return YEAR_RULE.get(report.crop_group, YEAR_RULE["vegetable"])


def _print_series_table(reports: Sequence[SeriesReport], limit: int) -> None:
    shown = reports[:limit]
    print(f"\n{'crop':<14}{'mandi':<26}{'obs':>5}{'dates':>7}{'span':>7}"
          f"{'dens':>7}{'gap':>6}{'feat':>7}{'rows':>8}  verdict")
    print("─" * 104)
    for r in shown:
        print(f"{r.crop[:13]:<14}{r.mandi[:25]:<26}{r.rows:>5}{r.distinct_dates:>7}"
              f"{r.span_days:>7}{r.density:>7.2f}{r.longest_gap_days:>6}"
              f"{r.feature_rows:>7}{r.training_rows:>8}  {r.verdict}")
    if len(reports) > limit:
        print(f"… and {len(reports) - limit} more series (--verbose to see all)")


def _print_crop_summary(reports: Sequence[SeriesReport]) -> None:
    print(f"\n{'crop':<16}{'group':<12}{'series':>8}{'obs':>8}{'rows':>9}"
          f"{'span yr':>9}{'need yr':>9}  status")
    print("─" * 88)
    by_crop: dict[str, list[SeriesReport]] = {}
    for r in reports:
        by_crop.setdefault(r.crop, []).append(r)

    for crop in sorted(by_crop):
        group = by_crop[crop]
        rows = sum(r.training_rows for r in group)
        obs = sum(r.rows for r in group)
        span_years = max(r.span_days for r in group) / 365.25
        floor_years, target_years = _rule_for(group[0])
        status = (
            "✅ meets floor" if span_years >= floor_years and rows > 0
            else "🟡 span ok, too sparse" if span_years >= floor_years
            else f"❌ needs {floor_years - span_years:.1f} more yr"
        )
        print(f"{crop[:15]:<16}{group[0].crop_group[:11]:<12}{len(group):>8}{obs:>8}"
              f"{rows:>9}{span_years:>9.1f}{floor_years:>9.1f}  {status}")


def _print_verdict(reports: Sequence[SeriesReport], frame: pd.DataFrame,
                   target_rows: int) -> int:
    total_rows = sum(r.training_rows for r in reports)
    live = [r for r in reports if r.training_rows > 0]
    crops = frame["commodity"].nunique()
    districts = frame["district"].nunique()

    print("\n" + "═" * 88)
    print("VERDICT")
    print("═" * 88)
    print(f"  series measured        {len(reports)}")
    print(f"  series producing rows  {len(live)}")
    print(f"  crops / districts      {crops} / {districts}")
    print(f"  training matrix rows   {total_rows:,}   (gate: {target_rows:,})")

    if total_rows >= target_rows:
        print(f"\n  ✅ READY. Build it:  python scripts/build_dataset.py --from "
              f"{frame['obs_date'].min().date()}")
        return 0

    # How much more collection? Assume the daily feed lands ~250 obs/year/series
    # once it is running, and that it covers the series we already know about.
    print(f"\n  ⛔ NOT READY — {TARGET_ROWS - total_rows:,} rows short.")

    if not live:
        print("\n  Every series failed the feature gate. The reason is density, not volume:")
        print(f"    build_features() needs {MIN_OBSERVATIONS} real observations inside a "
              f"{LOOKBACK_DAYS}-day window.")
        worst = max(reports, key=lambda r: r.distinct_dates) if reports else None
        if worst:
            print(f"    Best series ({worst.crop} @ {worst.mandi}) has "
                  f"{worst.distinct_dates} dates across {worst.span_days} days "
                  f"— longest gap {worst.longest_gap_days} days.")
        print("\n  This is a CONTINUITY problem. More one-off exports will not fix it;")
        print("  only a daily feed running every day will.")

    series_pool = max(len(reports), 1)
    rows_per_day = series_pool * len(HORIZONS) * (250 / 365.25)
    days_needed = int((target_rows - total_rows) / max(rows_per_day, 1e-9))
    print(f"\n  With the collector running daily across {series_pool} series,")
    print(f"  the gate arrives in roughly {days_needed} days "
          f"({days_needed / 30:.1f} months).")
    print("  Add mandis and crops to shorten that — rows scale linearly with series.")

    print("\n  Next actions:")
    print("    1. make up && make collect          — and put it on a schedule TODAY")
    print("    2. widen config/sources.yaml → ceda to all crops, start_date 2021-01-01")
    print("    3. fix unresolved mandi aliases in config/mandis.yaml")
    print("    4. make evaluate-baseline           — record the floor while you wait")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure whether there is enough data to train a model."
    )
    parser.add_argument("--csv", action="store_true",
                        help="read data/raw/mandi_history.csv instead of Postgres")
    parser.add_argument("--csv-path", default=None, help="override the CSV path")
    parser.add_argument("--verbose", action="store_true", help="list every series")
    parser.add_argument("--target-rows", type=int, default=TARGET_ROWS)
    args = parser.parse_args(argv)

    source = "csv" if args.csv else "postgres"
    print(f"\nBhav Setu — training data readiness  (source: {source})")
    print(f"gate: {MIN_OBSERVATIONS} real observations inside {LOOKBACK_DAYS} days, "
          f"horizons {HORIZONS}, label tolerance {LABEL_TOLERANCE_DAYS}d")

    try:
        frame = load_from_csv(args.csv_path) if args.csv else load_from_db()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — a dead DB must not look like no data
        print(f"\n⛔ could not read {source}: {type(exc).__name__}: {exc}")
        if not args.csv:
            print("   Is Postgres up?  make up      "
                  "Or measure the CSV instead:  --csv")
        return 2

    if frame.empty:
        print("\n⛔ no price observations at all.")
        return 1

    reports = measure(frame)
    _print_series_table(reports, limit=10_000 if args.verbose else 15)
    _print_crop_summary(reports)
    return _print_verdict(reports, frame, args.target_rows)


if __name__ == "__main__":
    raise SystemExit(main())
