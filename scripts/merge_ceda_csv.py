"""Turn CEDA's two-file export into the one canonical CSV the backfill expects.

    python scripts/merge_ceda_csv.py            # reads data/raw/*.csv
    python scripts/merge_ceda_csv.py --out data/raw/mandi_history.csv

CEDA exports prices and quantities separately:
    price_data*.csv     t, market_name, district_name, variety, p_min, p_max, p_modal
    quantity_data*.csv  t, market_name, district_name, qty

This joins them on (date, market) and writes ONE row per market per day.

Why collapse varieties here rather than let cleaners.collapse_daily do it: the
quantity file has no variety column, so its qty is a market-day total. Copying
that total onto each variety row would make the downstream sum count it several
times over, and leaving it on only one row would corrupt the arrival-weighted
modal price. Normalising the shape is this adapter's job; the cleaning rules
still run afterwards, untouched.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path side effect)

import pandas as pd

from core import logging as log
from core.config import settings
from core.errors import IngestionError

RAW_DIR: Path = settings.path("data", "raw")
DEFAULT_OUT: Path = RAW_DIR / "mandi_history.csv"

OUT_COLUMNS: list[str] = [
    "obs_date",
    "state",
    "district",
    "mandi",
    "commodity",
    "variety",
    "grade",
    "min_price",
    "max_price",
    "modal_price",
    "arrival_qtl",
]


def _read_group(pattern: str) -> pd.DataFrame:
    paths = sorted(glob.glob(str(RAW_DIR / pattern)))
    if not paths:
        return pd.DataFrame()
    frames = [pd.read_csv(p) for p in paths]
    out = pd.concat(frames, ignore_index=True)
    log.info("ceda_csv_read", pattern=pattern, files=len(paths), rows=len(out))
    return out


def merge(out_path: Path) -> pd.DataFrame:
    prices = _read_group("price_data*.csv")
    quantities = _read_group("quantity_data*.csv")

    if prices.empty:
        raise IngestionError(
            f"no price_data*.csv found in {RAW_DIR}. Download the Price export from CEDA first."
        )

    prices["t"] = pd.to_datetime(prices["t"], errors="coerce")
    prices = prices.dropna(subset=["t", "market_name", "p_modal"])

    for col in ("p_min", "p_max", "p_modal"):
        prices[col] = pd.to_numeric(prices[col], errors="coerce")

    # One row per (day, market): widest min/max seen, mean of the variety modals.
    daily = (
        prices.groupby(["t", "market_name", "district_name", "state_name"], as_index=False)
        .agg(
            min_price=("p_min", "min"),
            max_price=("p_max", "max"),
            modal_price=("p_modal", "mean"),
            varieties=("variety", "nunique"),
        )
    )
    log.info("ceda_csv_collapsed", price_rows=len(prices), daily_rows=len(daily))

    if not quantities.empty:
        quantities["t"] = pd.to_datetime(quantities["t"], errors="coerce")
        quantities["qty"] = pd.to_numeric(quantities["qty"], errors="coerce")
        qty_daily = (
            quantities.dropna(subset=["t", "market_name"])
            .groupby(["t", "market_name"], as_index=False)
            .agg(arrival_qtl=("qty", "sum"))
        )
        daily = daily.merge(qty_daily, on=["t", "market_name"], how="left")
        matched = int(daily["arrival_qtl"].notna().sum())
        log.info("ceda_csv_arrivals_joined", quantity_rows=len(quantities), matched=matched)
    else:
        daily["arrival_qtl"] = pd.NA
        log.warn("ceda_csv_no_quantities", hint="feature group B will be empty")

    out = pd.DataFrame(
        {
            "obs_date": daily["t"].dt.strftime("%Y-%m-%d"),
            "state": daily["state_name"],
            "district": daily["district_name"],
            "mandi": daily["market_name"],
            "commodity": "Onion",
            "variety": "",
            "grade": "",
            "min_price": daily["min_price"],
            "max_price": daily["max_price"],
            "modal_price": daily["modal_price"].round(2),
            "arrival_qtl": daily["arrival_qtl"],
        }
    )[OUT_COLUMNS].sort_values(["mandi", "obs_date"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    with_arrivals = int(out["arrival_qtl"].notna().sum())
    print(
        f"\n✅ wrote {out_path}\n"
        f"   rows        {len(out):,}\n"
        f"   markets     {out['mandi'].nunique()}\n"
        f"   dates       {out['obs_date'].min()} → {out['obs_date'].max()}\n"
        f"   with arrivals {with_arrivals:,} of {len(out):,}\n"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge CEDA price + quantity exports.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    merge(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
