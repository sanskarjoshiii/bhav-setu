"""Phase 2 acceptance: the data is in, it is clean, and we know how good it is.

Run:  make check-phase2     (or: cd backend && pytest tests/test_phase2_ingestion.py)
Requires `make backfill` to have run against the database from Phase 1.

Two groups:
  * pure rule tests — no database, they pin the cleaning contract
  * acceptance tests — read the real tables, these are the phase gate
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from core.config import settings
from core.db import get_conn
from ingestion import normalise_units
from ingestion.audit import REPORT_PATH
from ingestion.cleaners import (
    MAX_IMPUTE_GAP_DAYS,
    clean_frame,
    collapse_daily,
    flag_suspect,
    impute_gaps,
    reject_absurd,
    reject_inconsistent,
    reject_nonpositive,
)
from ingestion.entity_resolution import _Candidate, _prefix_match, normalise
from ingestion.routing import haversine_km
from ingestion.shocks import MIN_EXPECTED_EVENTS

pytestmark = pytest.mark.phase2

MIN_ROWS_PER_MANDI: int = 500
MIN_DENSE_MANDIS: int = 3


def scalar(sql: str, params: dict[str, Any] | None = None) -> Any:
    with get_conn() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings()]


def _series(dates: list[str], modal: list[float], **extra: Any) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(dates),
            "mandi_id": 1,
            "commodity_id": 1,
            "variety": "",
            "grade": "",
            "min_price": [m * 0.9 for m in modal],
            "max_price": [m * 1.1 for m in modal],
            "modal_price": modal,
            "arrival_qtl": 100.0,
        }
    )
    for key, value in extra.items():
        frame[key] = value
    return frame


# ══════════════════════════════════════════════════════════════════════════
# cleaning rules — no database needed
# ══════════════════════════════════════════════════════════════════════════

def test_reject_nonpositive_catches_zero_and_missing() -> None:
    frame = _series(["2024-01-01"] * 4, [1500.0, 0.0, 10.0, np.nan])
    assert list(reject_nonpositive(frame)) == [False, True, True, True]


def test_reject_inconsistent_catches_min_above_modal() -> None:
    frame = _series(["2024-01-01"] * 3, [1500.0, 1500.0, 1500.0])
    frame.loc[1, "min_price"] = 1600.0        # min > modal
    frame.loc[2, "max_price"] = 1400.0        # modal > max
    assert list(reject_inconsistent(frame)) == [False, True, True]


def test_reject_absurd_uses_only_past_data() -> None:
    """A 20x jump is impossible; a 3x jump is a real onion market and must survive."""
    dates = pd.bdate_range("2023-01-02", periods=40).strftime("%Y-%m-%d").tolist()
    modal = [1500.0] * 39 + [45000.0]
    flagged = reject_absurd(_series(dates, modal))
    assert flagged.iloc[-1], "20x+ spike should be rejected"
    assert not flagged.iloc[:-1].any()

    modal_real = [1500.0] * 39 + [4500.0]
    assert not reject_absurd(_series(dates, modal_real)).any(), "a 3x spike is real, keep it"


def test_flag_suspect_marks_but_does_not_delete() -> None:
    dates = pd.bdate_range("2023-01-02", periods=60).strftime("%Y-%m-%d").tolist()
    modal = [1500.0 + 5 * (i % 3) for i in range(59)] + [4200.0]
    flags = flag_suspect(_series(dates, modal))
    assert bool(flags.iloc[-1]) is True
    assert int(flags.fillna(False).sum()) == 1


def test_impute_gap_fills_short_gaps_and_leaves_long_ones() -> None:
    # 2024-01-01 Mon .. 2024-01-19 Fri; drop a 2-day gap and a 6-day gap
    calendar = pd.bdate_range("2024-01-01", "2024-01-19")
    dropped_short = {pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")}
    dropped_long = set(pd.bdate_range("2024-01-09", "2024-01-16"))
    kept = [d for d in calendar if d not in dropped_short | dropped_long]

    frame = _series([d.strftime("%Y-%m-%d") for d in kept], [1500.0] * len(kept))
    frame["is_imputed"] = False
    frame["suspect"] = False
    filled, n_imputed = impute_gaps(frame)

    assert n_imputed == len(dropped_short)
    filled_dates = set(pd.to_datetime(filled["obs_date"]))
    assert dropped_short <= filled_dates
    assert not (dropped_long & filled_dates), "gaps longer than 3 days must stay missing"
    assert filled.loc[filled["is_imputed"], "arrival_qtl"].isna().all(), \
        "an imputed row must not carry a fabricated arrival"


def test_imputed_rows_carry_the_flag() -> None:
    calendar = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", "2024-01-19")]
    kept = calendar[:2] + calendar[4:]
    cleaned, report = clean_frame(_series(kept, [1500.0] * len(kept)))
    assert report.imputed == 2
    assert cleaned.loc[cleaned["is_imputed"], "obs_date"].size == 2
    assert cleaned["is_imputed"].dtype == bool


def test_collapse_daily_is_arrival_weighted() -> None:
    frame = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "mandi_id": [1, 1],
            "commodity_id": [1, 1],
            "variety": ["Red", "Local"],
            "grade": ["", ""],
            "min_price": [1000.0, 1200.0],
            "max_price": [2000.0, 2200.0],
            "modal_price": [1000.0, 2000.0],
            "arrival_qtl": [900.0, 100.0],
        }
    )
    out = collapse_daily(frame)
    assert len(out) == 1
    assert out.loc[0, "modal_price"] == pytest.approx(1100.0)
    assert out.loc[0, "arrival_qtl"] == pytest.approx(1000.0)
    assert out.loc[0, "min_price"] == 1000.0 and out.loc[0, "max_price"] == 2200.0
    assert out.loc[0, "raw"]["varieties"] == ["Local", "Red"]


def test_bad_rows_are_rejected_before_the_daily_collapse() -> None:
    """A zero-price row must be thrown out, not averaged into its own day."""
    frame = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "mandi_id": [1, 1],
            "commodity_id": [1, 1],
            "variety": ["Red", "Local"],
            "grade": ["", ""],
            "min_price": [1400.0, 0.0],
            "max_price": [1700.0, 0.0],
            "modal_price": [1500.0, 0.0],
            "arrival_qtl": [500.0, 500.0],
        }
    )
    cleaned, report = clean_frame(frame)
    assert report.rejected["reject_nonpositive"] == 1
    assert len(cleaned) == 1
    assert cleaned.loc[0, "modal_price"] == pytest.approx(1500.0), \
        "the good price was diluted by a rejected row"


def test_units_are_normalised_to_quintals() -> None:
    frame = _series(["2024-01-01"], [18.6])          # ₹/kg
    frame["arrival_qtl"] = 9.0                        # tonnes
    out = normalise_units(frame, {"price": "rupees_per_kg", "arrival": "tonne"})
    assert out.loc[0, "modal_price"] == pytest.approx(1860.0)
    assert out.loc[0, "arrival_qtl"] == pytest.approx(90.0)


def test_unknown_unit_raises_instead_of_guessing() -> None:
    from core.errors import IngestionError

    with pytest.raises(IngestionError):
        normalise_units(_series(["2024-01-01"], [1500.0]),
                        {"price": "rupees_per_maund", "arrival": "quintal"})


# ══════════════════════════════════════════════════════════════════════════
# entity resolution and routing helpers
# ══════════════════════════════════════════════════════════════════════════

def test_normalise_strips_case_and_punctuation() -> None:
    assert normalise("Onion(Big)") == "onion big"
    assert normalise("  PIMPALGAON  BASWANT ") == "pimpalgaon baswant"


def test_prefix_match_handles_sub_yard_names() -> None:
    pool = [
        _Candidate(1, "Lasalgaon", "lasalgaon", "Nashik"),
        _Candidate(2, "Yeola", "yeola", "Nashik"),
    ]
    assert _prefix_match("lasalgaon vinchur", pool) is not None
    assert _prefix_match("lasalgaon vinchur", pool).entity_id == 1
    assert _prefix_match("kolhapur", pool) is None


def test_haversine_matches_known_distance() -> None:
    # Lasalgaon -> Nashik, roughly 55 km straight line
    km = haversine_km(20.1436, 74.2372, 19.9975, 73.7898)
    assert 45 < km < 65


# ══════════════════════════════════════════════════════════════════════════
# acceptance — these read the real database
# ══════════════════════════════════════════════════════════════════════════

def test_at_least_three_mandis_have_dense_history() -> None:
    counts = rows(
        "SELECT m.name, count(p.id) AS n FROM mandis m "
        "LEFT JOIN price_observations p ON p.mandi_id = m.id "
        "GROUP BY m.name ORDER BY n DESC"
    )
    dense = [r for r in counts if r["n"] >= MIN_ROWS_PER_MANDI]
    assert len(dense) >= MIN_DENSE_MANDIS, (
        f"only {len(dense)} mandi(s) have >= {MIN_ROWS_PER_MANDI} rows: "
        f"{[(r['name'], r['n']) for r in counts]}. "
        f"Open {REPORT_PATH.name} and swap the thin mandis in config/mandis.yaml."
    )


def test_no_nonpositive_prices_survived() -> None:
    assert scalar("SELECT count(*) FROM price_observations WHERE modal_price <= 10") == 0


def test_no_self_contradicting_rows_survived() -> None:
    bad = scalar(
        "SELECT count(*) FROM price_observations "
        "WHERE (min_price IS NOT NULL AND min_price > modal_price) "
        "   OR (max_price IS NOT NULL AND modal_price > max_price)"
    )
    assert bad == 0


def test_every_row_has_a_source() -> None:
    sources = [r["source"] for r in rows("SELECT DISTINCT source FROM price_observations")]
    assert sources, "price_observations is empty — run make backfill"
    assert set(sources) <= {"csv_backfill", "agmarknet_api", "seed_demo"}, sources


def test_imputed_runs_never_exceed_the_configured_gap() -> None:
    """A forward-fill longer than 3 business days would be inventing prices."""
    longest = scalar(
        """
        WITH flagged AS (
            SELECT mandi_id, obs_date, is_imputed,
                   row_number() OVER (PARTITION BY mandi_id ORDER BY obs_date)
                 - row_number() OVER (PARTITION BY mandi_id, is_imputed ORDER BY obs_date) AS grp
            FROM price_observations
        )
        SELECT coalesce(max(n), 0) FROM (
            SELECT count(*) AS n FROM flagged WHERE is_imputed GROUP BY mandi_id, grp
        ) runs
        """
    )
    assert longest <= MAX_IMPUTE_GAP_DAYS, f"found an imputed run of {longest} days"


def test_weather_exists_for_every_mandi() -> None:
    missing = rows(
        "SELECT m.name FROM mandis m "
        "WHERE NOT EXISTS (SELECT 1 FROM weather_daily w WHERE w.mandi_id = m.id)"
    )
    assert not missing, f"no weather for: {[r['name'] for r in missing]}"


def test_forecast_rows_never_overwrote_history() -> None:
    """Anything older than today must be a real observation, not a forecast."""
    stale_forecasts = scalar(
        "SELECT count(*) FROM weather_daily WHERE is_forecast AND obs_date < CURRENT_DATE"
    )
    assert stale_forecasts == 0
    assert scalar("SELECT count(*) FROM weather_daily WHERE NOT is_forecast") > 0
    assert scalar("SELECT count(*) FROM weather_daily WHERE is_forecast") > 0


def test_shock_events_loaded_and_well_formed() -> None:
    n = scalar("SELECT count(*) FROM shock_events")
    assert n >= MIN_EXPECTED_EVENTS, (
        f"only {n} shock events. Fill data/manual/shock_events.csv with ~20 real "
        f"onion policy events — this is a manual step."
    )
    assert scalar("SELECT count(*) FROM shock_events WHERE direction NOT IN (-1, 1)") == 0
    assert scalar("SELECT count(*) FROM shock_events WHERE magnitude NOT IN (1, 2, 3)") == 0
    assert scalar("SELECT count(*) FROM shock_events WHERE decay_days <= 0") == 0
    assert scalar("SELECT count(*) FROM shock_events WHERE commodity_id IS NULL") == 0


def test_distance_cache_covers_village_to_every_mandi() -> None:
    village = settings.mandis.reference_village
    n_mandis = scalar("SELECT count(*) FROM mandis WHERE active")
    cached = scalar(
        "SELECT count(*) FROM distance_cache WHERE from_lat = :lat AND from_lon = :lon",
        {"lat": round(float(village["lat"]), 4), "lon": round(float(village["lon"]), 4)},
    )
    assert cached >= n_mandis, f"{cached} cached routes for {n_mandis} mandis"
    assert scalar("SELECT count(*) FROM distance_cache WHERE road_km <= 0") == 0


def test_ingestion_runs_were_recorded() -> None:
    jobs = [r["job"] for r in rows(
        "SELECT DISTINCT job FROM ingestion_runs WHERE status IN ('ok', 'partial')"
    )]
    assert "csv_backfill" in jobs, f"no successful csv_backfill run recorded: {jobs}"
    assert "weather" in jobs, f"no successful weather run recorded: {jobs}"


def test_audit_report_exists_and_names_every_mandi() -> None:
    assert REPORT_PATH.exists(), f"{REPORT_PATH} missing — run make backfill"
    body = REPORT_PATH.read_text(encoding="utf-8")
    for mandi in settings.mandis.mandis:
        assert mandi["name"] in body, f"{mandi['name']} missing from the audit report"
    assert "USABLE" in body


def test_history_spans_at_least_two_years() -> None:
    span = rows(
        "SELECT min(obs_date) AS lo, max(obs_date) AS hi FROM price_observations"
    )[0]
    assert span["lo"] is not None, "price_observations is empty — run make backfill"
    days = (span["hi"] - span["lo"]).days
    assert days >= 700, f"history spans only {days} days ({span['lo']} .. {span['hi']})"
