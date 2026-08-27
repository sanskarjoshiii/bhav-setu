"""Phase 2.3 — cleaning rules, one named function per rule.

Each rule is a separate function returning a boolean mask so `audit.py` can report
rejections *by rule* rather than one useless total.

| rule                | condition                                   | action              |
|---------------------|---------------------------------------------|---------------------|
| reject_nonpositive  | modal <= min_modal_price                    | reject              |
| reject_inconsistent | min > modal or modal > max                  | reject              |
| reject_absurd       | modal > 20 x trailing median (90d, past)    | reject              |
| flag_suspect        | |z| of daily log-return > 6                 | keep, suspect=true  |
| impute_gap          | missing business day, gap <= 3              | ffill, is_imputed   |
| leave_gap           | missing business day, gap > 3               | leave missing       |

⚠️ No winsorising. A tripling onion price is real and is the event we exist to
predict. Only physically impossible values are removed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core.config import settings

_CFG = settings.sources.cleaning
MIN_MODAL_PRICE: float = float(_CFG.min_modal_price)
ABSURD_MULTIPLE: float = float(_CFG.absurd_multiple)
TRAILING_MEDIAN_WINDOW: int = int(_CFG.trailing_median_window)
SUSPECT_ZSCORE: float = float(_CFG.suspect_zscore)
SUSPECT_WINDOW: int = int(_CFG.suspect_window)
MAX_IMPUTE_GAP_DAYS: int = int(_CFG.max_impute_gap_days)
COLLAPSE_VARIETIES: bool = bool(_CFG.collapse_varieties)

# Canonical column set every ingestion source produces before cleaning.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "obs_date",
    "mandi_id",
    "commodity_id",
    "variety",
    "grade",
    "min_price",
    "max_price",
    "modal_price",
    "arrival_qtl",
)

SERIES_KEY: tuple[str, ...] = ("mandi_id", "commodity_id", "variety", "grade")


@dataclass
class CleaningReport:
    """Counts for the audit report. `rejected` is keyed by rule name."""

    rows_in: int = 0
    rows_after_collapse: int = 0
    rows_kept: int = 0
    imputed: int = 0
    suspect: int = 0
    rejected: Counter[str] = field(default_factory=Counter)

    @property
    def rows_rejected(self) -> int:
        return int(sum(self.rejected.values()))

    def merge(self, other: "CleaningReport") -> None:
        self.rows_in += other.rows_in
        self.rows_after_collapse += other.rows_after_collapse
        self.rows_kept += other.rows_kept
        self.imputed += other.imputed
        self.suspect += other.suspect
        self.rejected.update(other.rejected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_in": self.rows_in,
            "rows_after_collapse": self.rows_after_collapse,
            "rows_kept": self.rows_kept,
            "rows_rejected": self.rows_rejected,
            "imputed": self.imputed,
            "suspect": self.suspect,
            "rejected_by_rule": dict(self.rejected),
        }


# ── row-level rules ───────────────────────────────────────────────────────

def reject_nonpositive(df: pd.DataFrame) -> pd.Series:
    """A zero or missing modal price is a data-entry hole, not a cheap market."""
    modal = pd.to_numeric(df["modal_price"], errors="coerce")
    return modal.isna() | (modal <= MIN_MODAL_PRICE)


def reject_inconsistent(df: pd.DataFrame) -> pd.Series:
    """min > modal or modal > max — the row contradicts itself."""
    lo = pd.to_numeric(df["min_price"], errors="coerce")
    hi = pd.to_numeric(df["max_price"], errors="coerce")
    modal = pd.to_numeric(df["modal_price"], errors="coerce")
    return ((lo > modal) & lo.notna()) | ((modal > hi) & hi.notna())


# ── series-level rules (need the mandi's own history, in date order) ──────

def reject_absurd(series: pd.DataFrame) -> pd.Series:
    """modal > 20 x the trailing 90-day median of the *past* only.

    The window is shifted by one so a spike is never compared against itself.
    """
    modal = pd.to_numeric(series["modal_price"], errors="coerce")
    trailing = (
        modal.shift(1)
        .rolling(TRAILING_MEDIAN_WINDOW, min_periods=10)
        .median()
    )
    return (modal > ABSURD_MULTIPLE * trailing) & trailing.notna()


def reject_collapsed(series: pd.DataFrame) -> pd.Series:
    """modal < the trailing 90-day median / 20 — the downward twin of reject_absurd.

    `reject_absurd` deliberately only looks upward, because a tripling onion
    price is real and winsorising it would delete the exact event we exist to
    predict. But that asymmetry let the opposite error through untouched, and it
    is not the same kind of number: a crop does not lose 99.9% of its value
    overnight. Measured on the CEDA pull, this let grapes through at ₹11/quintal
    against a ₹6,000 median — eleven paise a kilo — along with potato at ₹12 and
    okra at ₹18. 394 rows, 0.22% of the matrix.

    They were invisible in pinball loss (a few rupees of absolute error) and
    devastating in MAPE, which divides by the truth: one row at ₹11 predicted as
    ₹1,200 contributes a 10,800% error on its own. That single defect pushed
    h=3 MAPE from the mid-teens to 44% and non-monotonic across horizons, which
    is what exposed it.

    Rejecting downward is safe in a way that rejecting upward would not be,
    because the floor is the *trailing* median: a genuine seasonal glut halves a
    price over weeks and drags the median with it. Only a one-day cliff trips
    this.
    """
    modal = pd.to_numeric(series["modal_price"], errors="coerce")
    trailing = (
        modal.shift(1)
        .rolling(TRAILING_MEDIAN_WINDOW, min_periods=10)
        .median()
    )
    return (modal < trailing / ABSURD_MULTIPLE) & trailing.notna()


def flag_suspect(series: pd.DataFrame) -> pd.Series:
    """Rolling z-score of the daily log-return above 6 — keep it, but mark it.

    The window is shifted by one: a jump must be judged against the days before
    it, not against a window it is itself inflating.
    """
    modal = pd.to_numeric(series["modal_price"], errors="coerce")
    log_return = np.log(modal).diff()
    past = log_return.shift(1)
    mean = past.rolling(SUSPECT_WINDOW, min_periods=10).mean()
    std = past.rolling(SUSPECT_WINDOW, min_periods=10).std()
    z = (log_return - mean) / std.replace(0.0, np.nan)
    return (z.abs() > SUSPECT_ZSCORE).fillna(False)


def impute_gaps(series: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Forward-fill runs of <= 3 missing business days; leave longer gaps missing.

    Every inserted row carries is_imputed=True. Rule: never forward-fill silently.
    """
    if series.empty:
        return series, 0

    indexed = series.set_index("obs_date").sort_index()
    calendar = pd.bdate_range(indexed.index.min(), indexed.index.max())
    reindexed = indexed.reindex(calendar)
    missing = reindexed["modal_price"].isna()
    if not missing.any():
        return series, 0

    # Length of each consecutive run of missing days.
    run_id = (missing != missing.shift()).cumsum()
    run_len = missing.groupby(run_id).transform("size")
    fillable = missing & (run_len <= MAX_IMPUTE_GAP_DAYS)

    filled = reindexed.ffill()
    filled["is_imputed"] = False
    filled.loc[fillable, "is_imputed"] = True
    filled = filled[~missing | fillable]

    # A leading gap has nothing to carry forward.
    filled = filled[filled["modal_price"].notna()]
    filled.index.name = "obs_date"
    out = filled.reset_index()
    out["arrival_qtl"] = out["arrival_qtl"].where(~out["is_imputed"])   # never fabricate arrivals
    return out, int(out["is_imputed"].sum())


# ── orchestration ─────────────────────────────────────────────────────────

def collapse_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Merge same-day rows that differ only by variety/grade into one series.

    Modal price is arrival-weighted (a 900-quintal Red lot should outweigh a
    12-quintal Local lot); with no arrivals recorded it falls back to the mean.
    The source varieties are kept in `raw` so nothing is silently lost.
    """
    if not COLLAPSE_VARIETIES or df.empty:
        return df

    work = df.copy()
    work["arrival_qtl"] = pd.to_numeric(work["arrival_qtl"], errors="coerce")
    work["modal_price"] = pd.to_numeric(work["modal_price"], errors="coerce")
    work["_w"] = work["arrival_qtl"].fillna(0.0).clip(lower=0.0)

    groups = work.groupby(["obs_date", "mandi_id", "commodity_id"], sort=False)
    rows: list[dict[str, Any]] = []
    for (obs_date, mandi_id, commodity_id), g in groups:
        weights = g["_w"]
        if weights.sum() > 0:
            modal = float(np.average(g["modal_price"], weights=weights))
        else:
            modal = float(g["modal_price"].mean())
        rows.append(
            {
                "obs_date": obs_date,
                "mandi_id": mandi_id,
                "commodity_id": commodity_id,
                "variety": "",
                "grade": "",
                "min_price": _safe_min(g["min_price"]),
                "max_price": _safe_max(g["max_price"]),
                "modal_price": modal,
                "arrival_qtl": float(weights.sum()) if weights.sum() > 0 else None,
                "raw": {
                    "varieties": sorted({str(v) for v in g["variety"].fillna("") if str(v)}),
                    "grades": sorted({str(v) for v in g["grade"].fillna("") if str(v)}),
                    "n_source_rows": int(len(g)),
                },
            }
        )
    return pd.DataFrame(rows)


def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Full pipeline: collapse -> row rules -> absurd -> suspect -> impute.

    Input needs CANONICAL_COLUMNS. Output is ready for upsert and carries
    `is_imputed`, `suspect` and `raw`.
    """
    report = CleaningReport(rows_in=int(len(df)))
    if df.empty:
        return df.assign(is_imputed=False, suspect=False), report

    # Row rules run BEFORE the collapse. A zero-price row merged into its day
    # would quietly drag a legitimate price down instead of being rejected.
    work = df
    for rule in (reject_nonpositive, reject_inconsistent):
        mask = rule(work)
        n = int(mask.sum())
        if n:
            report.rejected[rule.__name__] += n
            work = work[~mask]
    if work.empty:
        return work.assign(is_imputed=False, suspect=False), report

    work = collapse_daily(work)
    if "raw" not in work.columns:
        work["raw"] = None
    report.rows_after_collapse = int(len(work))

    cleaned_parts: list[pd.DataFrame] = []
    for _, group in work.groupby(["mandi_id", "commodity_id"], sort=False):
        series = group.sort_values("obs_date").reset_index(drop=True)

        absurd = reject_absurd(series)
        n_absurd = int(absurd.sum())
        if n_absurd:
            report.rejected["reject_absurd"] += n_absurd
            series = series[~absurd].reset_index(drop=True)

        collapsed = reject_collapsed(series)
        n_collapsed = int(collapsed.sum())
        if n_collapsed:
            report.rejected["reject_collapsed"] += n_collapsed
            series = series[~collapsed].reset_index(drop=True)

        series["suspect"] = flag_suspect(series).fillna(False)
        series["is_imputed"] = False
        series, n_imputed = impute_gaps(series)
        report.imputed += n_imputed
        cleaned_parts.append(series)

    out = pd.concat(cleaned_parts, ignore_index=True) if cleaned_parts else work
    out["suspect"] = out["suspect"].fillna(False).astype(bool)
    out["is_imputed"] = out["is_imputed"].fillna(False).astype(bool)
    out["variety"] = out["variety"].fillna("")
    out["grade"] = out["grade"].fillna("")
    report.rows_kept = int(len(out))
    report.suspect = int(out["suspect"].sum())
    return out, report


def _safe_min(s: pd.Series) -> float | None:
    v = pd.to_numeric(s, errors="coerce").min()
    return None if pd.isna(v) else float(v)


def _safe_max(s: pd.Series) -> float | None:
    v = pd.to_numeric(s, errors="coerce").max()
    return None if pd.isna(v) else float(v)
