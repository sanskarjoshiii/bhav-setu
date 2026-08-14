"""Profile a candidate mandi-price CSV before you wire it into the pipeline.

    python scripts/inspect_dataset.py <path-to.csv>

Answers the four questions that decide whether a download is usable at all:
  1. Does it carry the columns Phase 2 needs — especially arrival_qtl?
  2. Does it contain the crops in config/crops.yaml?
  3. Does it contain the mandis in config/mandis.yaml?
  4. How many days per market does it actually cover?

Ends with a verdict and, when usable, the exact `csv_backfill.columns` block to
paste into config/sources.yaml. Reads in chunks, so a multi-GB file is fine.

Nothing is written to the database and no file is modified.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import _bootstrap  # noqa: F401  (sys.path side effect)

import pandas as pd
from rapidfuzz import fuzz

from core.config import settings
from core.errors import ConfigError
from ingestion.entity_resolution import normalise

# canonical field -> header spellings seen in the wild, normalised for comparison
HEADER_CANDIDATES: dict[str, tuple[str, ...]] = {
    "obs_date": ("price date", "arrival date", "date", "reported date", "obs date"),
    "state": ("state", "state name"),
    "district": ("district", "district name"),
    "mandi": ("market", "market name", "mandi", "mandi name", "market centre"),
    "commodity": ("commodity", "commodity name"),
    "variety": ("variety", "variety name"),
    "grade": ("grade",),
    "min_price": ("min price", "min price rs quintal", "minimum price", "min_x0020_price"),
    "max_price": ("max price", "max price rs quintal", "maximum price", "max_x0020_price"),
    "modal_price": ("modal price", "modal price rs quintal", "modal_x0020_price"),
    "arrival": ("arrival", "arrivals", "arrival qty", "arrivals qty", "arrival tonnes",
                "arrivals in qtl", "quantity"),
}

# Without these, Phase 2 cannot build a single usable row.
ESSENTIAL: tuple[str, ...] = ("obs_date", "mandi", "commodity", "modal_price")

DATE_FORMATS: tuple[str, ...] = (
    "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d-%b-%Y",
)

CHUNK_SIZE: int = 200_000


def detect_columns(headers: list[str]) -> dict[str, str | None]:
    """Map canonical field -> actual header, or None when absent."""
    normalised = {normalise(h): h for h in headers}
    found: dict[str, str | None] = {}
    for field, candidates in HEADER_CANDIDATES.items():
        match: str | None = None
        for candidate in candidates:
            if candidate in normalised:
                match = normalised[candidate]
                break
        if match is None:                      # fall back to fuzzy, high bar
            best_score = 0.0
            for norm_header, original in normalised.items():
                score = max(fuzz.token_sort_ratio(candidate, norm_header)
                            for candidate in candidates)
                if score > best_score and score >= 88:
                    best_score, match = score, original
        found[field] = match
    return found


def detect_date_format(sample: pd.Series) -> str | None:
    values = sample.dropna().astype(str).head(200)
    if values.empty:
        return None
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(values, format=fmt, errors="coerce")
        if parsed.notna().mean() > 0.95:
            return fmt
    return None


def iter_chunks(path: Path, usecols: list[str]) -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(path, chunksize=CHUNK_SIZE, usecols=usecols, low_memory=False)


def configured_crop_aliases() -> dict[str, set[str]]:
    """crop name -> its normalised aliases, from config/crops.yaml."""
    out: dict[str, set[str]] = {}
    for crop, raw_spec in settings.crops.to_dict().items():
        spec = raw_spec.to_dict() if hasattr(raw_spec, "to_dict") else dict(raw_spec)
        aliases = set(spec.get("aliases", [])) | {crop}
        out[crop] = {normalise(str(a)) for a in aliases}
    return out


def configured_mandis() -> dict[str, str]:
    """normalised mandi name -> display name, from config/mandis.yaml."""
    return {normalise(m["name"]): m["name"] for m in settings.mandis.mandis}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile a mandi-price CSV.")
    parser.add_argument("path", type=Path, help="CSV to inspect")
    parser.add_argument("--top", type=int, default=8, help="markets to list per crop")
    args = parser.parse_args(argv)

    path: Path = args.path
    if not path.exists():
        raise ConfigError(f"no such file: {path}")

    size_mb = path.stat().st_size / 1024 / 1024
    headers = list(pd.read_csv(path, nrows=0).columns)
    cols = detect_columns(headers)

    print(f"\nFILE   {path}")
    print(f"       {size_mb:,.1f} MB")
    print(f"\nCOLUMNS DETECTED ({len(headers)} in file)")
    for field in HEADER_CANDIDATES:
        actual = cols[field]
        mark = "ok " if actual else ("MISSING" if field in ESSENTIAL else "absent ")
        print(f"  {mark:>8}  {field:<12} {actual or '-'}")

    missing_essential = [f for f in ESSENTIAL if cols[f] is None]
    if missing_essential:
        print(f"\n❌ UNUSABLE — no {', '.join(missing_essential)} column.")
        return 1

    has_arrivals = cols["arrival"] is not None
    read_cols = [c for c in cols.values() if c is not None]

    date_fmt = detect_date_format(pd.read_csv(path, nrows=500, usecols=[cols["obs_date"]])[cols["obs_date"]])
    if date_fmt is None:
        print(f"\n❌ UNUSABLE — cannot parse '{cols['obs_date']}'; tried {DATE_FORMATS}")
        return 1

    # ── single pass ───────────────────────────────────────────────────────
    rows = 0
    states: Counter[str] = Counter()
    commodities: Counter[str] = Counter()
    days_by_key: defaultdict[tuple[str, str, str], set[date]] = defaultdict(set)
    lo: pd.Timestamp | None = None
    hi: pd.Timestamp | None = None

    crop_aliases = configured_crop_aliases()
    wanted_norms = {n for norms in crop_aliases.values() for n in norms}

    for chunk in iter_chunks(path, read_cols):
        rows += len(chunk)
        if cols["state"]:
            states.update(chunk[cols["state"]].dropna().astype(str))
        commodity_series = chunk[cols["commodity"]].dropna().astype(str)
        commodities.update(commodity_series)

        parsed = pd.to_datetime(chunk[cols["obs_date"]], format=date_fmt, errors="coerce")
        valid = parsed.dropna()
        if not valid.empty:
            lo = valid.min() if lo is None else min(lo, valid.min())
            hi = valid.max() if hi is None else max(hi, valid.max())

        keep = chunk[cols["commodity"]].astype(str).map(normalise).isin(wanted_norms)
        if keep.any():
            sub = chunk[keep]
            sub_dates = parsed[keep]
            state_col = (sub[cols["state"]].astype(str) if cols["state"]
                         else pd.Series([""] * len(sub), index=sub.index))
            for commodity, market, state_name, when in zip(
                sub[cols["commodity"]].astype(str),
                sub[cols["mandi"]].astype(str),
                state_col,
                sub_dates,
            ):
                if pd.notna(when):
                    days_by_key[(commodity, market, state_name)].add(when.date())

    span_days = (hi - lo).days + 1 if lo is not None and hi is not None else 0
    print(f"\nROWS   {rows:,}")
    print(f"DATES  {lo:%Y-%m-%d} -> {hi:%Y-%m-%d}  ({span_days} days, format '{date_fmt}')")

    print(f"\nSTATES ({len(states)})")
    for name, count in states.most_common(12):
        print(f"  {count:>10,}  {name}")

    print(f"\nCOMMODITIES ({len(commodities)})")
    for name, count in commodities.most_common(15):
        print(f"  {count:>10,}  {name}")
    if len(commodities) > 15:
        print(f"  ... and {len(commodities) - 15} more")

    # ── does it contain what we are configured to look for? ───────────────
    print("\nCONFIGURED CROPS (config/crops.yaml)")
    crops_present: list[str] = []
    present_norms = {normalise(c) for c in commodities}
    for crop, aliases in crop_aliases.items():
        hits = sorted(a for a in aliases if a in present_norms)
        if hits:
            crops_present.append(crop)
            total = sum(c for name, c in commodities.items() if normalise(name) in aliases)
            print(f"  ok        {crop:<12} {total:>9,} rows  (matched: {', '.join(hits)})")
        else:
            print(f"  MISSING   {crop:<12} no alias found in this file")

    print("\nCONFIGURED MANDIS (config/mandis.yaml)")
    wanted_mandis = configured_mandis()
    market_norms = {normalise(m) for (_, m, _) in days_by_key}
    if not market_norms:                       # no configured crop matched; scan all markets
        market_norms = set()
    mandi_hits = 0
    for norm, display in wanted_mandis.items():
        exact = norm in market_norms
        near = max((fuzz.token_sort_ratio(norm, m) for m in market_norms), default=0.0)
        if exact:
            mandi_hits += 1
            print(f"  ok        {display}")
        elif near >= 90:
            mandi_hits += 1
            print(f"  fuzzy     {display}  (closest score {near:.0f})")
        else:
            print(f"  MISSING   {display}")

    # ── coverage of the densest markets ───────────────────────────────────
    if days_by_key:
        print(f"\nDENSEST MARKETS for configured crops (of {span_days} days)")
        for crop in crops_present:
            aliases = crop_aliases[crop]
            ranked = sorted(
                ((len(d), commodity, market, state_name)
                 for (commodity, market, state_name), d in days_by_key.items()
                 if normalise(commodity) in aliases),
                reverse=True,
            )[: args.top]
            if not ranked:
                continue
            print(f"  {crop}")
            for n_days, _, market, state_name in ranked:
                pct = 100 * n_days / span_days if span_days else 0
                where = f"{market}, {state_name}" if state_name else market
                print(f"    {n_days:>4} days ({pct:>4.0f}%)  {where}")

    # ── verdict ───────────────────────────────────────────────────────────
    problems: list[str] = []
    if not crops_present:
        problems.append("none of the crops in config/crops.yaml appear in this file")
    if mandi_hits == 0:
        problems.append("none of the mandis in config/mandis.yaml appear in this file")
    if not has_arrivals:
        problems.append(
            "no arrivals column — feature group B (arr_lag_*, arr_vs_ma30, "
            "arr_momentum, price_arrival_elasticity) and mandi_liquidity cannot be built"
        )
    if span_days < 365:
        problems.append(f"only {span_days} days of history; the plan assumes 2-3 years")

    print("\n" + "─" * 70)
    if not problems:
        print("✅ USABLE — matches the configured crops and mandis, arrivals present.")
    elif not crops_present or mandi_hits == 0:
        print("❌ UNUSABLE as configured:")
        for problem in problems:
            print(f"   • {problem}")
        print("\n   Either pick a different download, or update config/crops.yaml and")
        print("   config/mandis.yaml to something this file actually contains.")
    else:
        print("⚠️  USABLE WITH GAPS:")
        for problem in problems:
            print(f"   • {problem}")

    # ── the config block to paste ─────────────────────────────────────────
    if crops_present and mandi_hits:
        print("\nPaste into config/sources.yaml under csv_backfill:")
        print("  columns:")
        for field in ("obs_date", "state", "district", "mandi", "commodity",
                      "variety", "grade", "min_price", "max_price", "modal_price"):
            if cols[field]:
                print(f"    {field}: {cols[field]}")
        if cols["arrival"]:
            print(f"    arrival: {cols['arrival']}")
        print(f'  date_format: "{date_fmt}"')

    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
