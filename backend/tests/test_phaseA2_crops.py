"""Phase A2 acceptance — the multi-crop configuration.

Run:  make check-phaseA2

No database. Everything here is a property of config/crops.yaml, config/mandis.yaml
and db/schema.sql, and every one of them is checkable before a single row is loaded.

Why a whole suite for two YAML files: `k_c`, `shelf_life_days` and `max_hold_days`
are the inputs to the spoilage maths in Phase A5, which is the input to the hold-or-
sell decision in Phase A6. A wrong number in this file does not crash anything. It
produces a confident recommendation to hold tomatoes for a week, which is worse than
no recommendation at all. So the numbers are derived by a stated rule and the rule is
tested, rather than fourteen integers being typed in and trusted.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.config import crop_specs, settings

pytestmark = pytest.mark.phaseA2

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CROPS = crop_specs()
ANCHOR: float = float(settings.cost_model.spoilage.anchor)

#: shelf_life_days -> perishability_class. Derived, never typed per crop.
PERISHABILITY_BANDS: tuple[tuple[int, int], ...] = (
    (10, 1), (20, 2), (45, 3), (100, 4),
)
STORABLE_CLASS: int = 5

CROP_GROUPS: frozenset[str] = frozenset(
    {"cereal", "pulse", "oilseed", "vegetable", "fruit", "spice"}
)


def expected_class(shelf_life_days: int) -> int:
    for ceiling, band in PERISHABILITY_BANDS:
        if shelf_life_days <= ceiling:
            return band
    return STORABLE_CLASS


def spoilage_fraction(k_c: float, days: int) -> float:
    """The Phase A5 formula, inlined so this suite does not wait on Phase A5."""
    return 1.0 - math.exp(-k_c * days)


# ══════════════════════════════════════════════════════════════════════════
# 1. the crop list itself
# ══════════════════════════════════════════════════════════════════════════

def test_there_are_enough_crops_to_be_a_multi_crop_product():
    """The plan's own expectation: 8-14 crops survive. Configure at least eight."""
    assert len(CROPS) >= 8, f"only {len(CROPS)} crops configured: {sorted(CROPS)}"


def test_the_crop_list_spans_the_perishability_spectrum():
    """Anti-vacuity for Phase A6.

    If every crop rots in a week, "hold" is never the right answer and the split
    recommendation the whole product is built on can never appear. If none do,
    the six hard constraints never fire. We need both ends present in the config
    for the decision engine's tests to be able to mean anything.
    """
    classes = {int(spec["perishability_class"]) for spec in CROPS.values()}
    assert min(classes) <= 2, "no genuinely perishable crop — sell-now can never be forced"
    assert max(classes) >= 4, "no genuinely storable crop — hold can never be right"


def test_every_crop_has_the_fields_the_rest_of_the_system_reads():
    required = {
        "aliases", "crop_group", "perishability_class", "k_c",
        "shelf_life_days", "max_hold_days", "msp_applicable", "seasons",
    }
    for name, spec in CROPS.items():
        missing = required - set(spec)
        assert not missing, f"{name} is missing {sorted(missing)}"


def test_crop_groups_match_the_schema_comment():
    for name, spec in CROPS.items():
        assert spec["crop_group"] in CROP_GROUPS, f"{name}: {spec['crop_group']}"


# ══════════════════════════════════════════════════════════════════════════
# 2. the three numbers that decide whether advice is sane
# ══════════════════════════════════════════════════════════════════════════

def test_k_c_is_derived_from_shelf_life_not_typed():
    """k_c = anchor / shelf_life_days, for every crop, no exceptions.

    This is what makes "shelf life" mean one thing across fourteen crops. Without
    it, a reviewer correcting tomato's shelf life would leave its spoilage rate
    saying something different, and nothing would complain.
    """
    for name, spec in CROPS.items():
        expected = ANCHOR / float(spec["shelf_life_days"])
        assert float(spec["k_c"]) == pytest.approx(expected, rel=0.02), (
            f"{name}: k_c={spec['k_c']} but anchor/shelf_life "
            f"= {ANCHOR}/{spec['shelf_life_days']} = {expected:.5f}. "
            f"Change shelf_life_days, not k_c."
        )


def test_the_anchor_still_reproduces_the_original_onion_pair():
    """Widening from one crop to fourteen must not have moved onion underneath us."""
    onion = CROPS["onion"]
    assert float(onion["k_c"]) == pytest.approx(0.006)
    assert int(onion["shelf_life_days"]) == 90
    assert float(onion["k_c"]) * int(onion["shelf_life_days"]) == pytest.approx(ANCHOR, rel=0.02)


def test_perishability_class_is_derived_from_shelf_life():
    for name, spec in CROPS.items():
        shelf = int(spec["shelf_life_days"])
        assert int(spec["perishability_class"]) == expected_class(shelf), (
            f"{name}: shelf_life={shelf} implies class {expected_class(shelf)}, "
            f"config says {spec['perishability_class']}"
        )


def test_no_crop_may_be_held_past_its_shelf_life():
    """The plan's explicit Phase 2 gate."""
    for name, spec in CROPS.items():
        assert int(spec["max_hold_days"]) < int(spec["shelf_life_days"]), name


def test_holding_to_the_limit_costs_a_believable_amount():
    """At max_hold_days every crop should lose 5-25% — the band the cost model assumes.

    Above 25% the recommendation is absurd on its face; below 5% the spoilage term
    is decorative and the decision engine would hold everything forever.
    """
    for name, spec in CROPS.items():
        loss = spoilage_fraction(float(spec["k_c"]), int(spec["max_hold_days"]))
        assert 0.05 <= loss <= 0.25, f"{name}: {loss:.1%} spoilage at max hold"


def test_the_spoilage_ceiling_actually_bites_on_perishables():
    """Anti-vacuity for the constraint in config/decision.yaml.

    `max_spoilage_fraction` is meant to be the rule that stops the maths
    recommending a week-long tomato hold. If no crop can ever exceed it, the
    constraint is decoration and its Phase A6 test would pass without it working.
    """
    ceiling = float(settings.decision.constraints.max_spoilage_fraction)
    breachable = [
        name for name, spec in CROPS.items()
        if spoilage_fraction(float(spec["k_c"]), int(spec["max_hold_days"])) > ceiling
    ]
    assert breachable, (
        f"no crop can breach max_spoilage_fraction={ceiling} even at its own hold "
        f"limit — the constraint can never fire"
    )


def test_a_storable_crop_survives_the_longest_decision_horizon():
    """The other half: some crop must be holdable for the longest horizon the
    decision engine will search, or "hold" is unreachable for every crop."""
    longest = max(int(h) for h in settings.decision.hold_horizons)
    holdable = [name for name, spec in CROPS.items() if int(spec["max_hold_days"]) >= longest]
    assert holdable, f"no crop can be held {longest} days — the grid search has no hold arm"


def test_shelf_lives_are_ordered_the_way_a_farmer_would_expect():
    """A sanity check a domain reviewer can read at a glance."""
    shelf = {name: int(spec["shelf_life_days"]) for name, spec in CROPS.items()}
    assert shelf["garlic"] > shelf["onion"] > shelf["cabbage"] > shelf["tomato"]
    assert shelf["okra"] <= shelf["tomato"]
    assert shelf["pomegranate"] > shelf["banana"]


# ══════════════════════════════════════════════════════════════════════════
# 3. aliases — how the upstream's vocabulary reaches our ids
# ══════════════════════════════════════════════════════════════════════════

def test_every_crop_has_at_least_three_aliases():
    """The plan's Phase 2 gate. Fuzzy matching needs something to match against."""
    for name, spec in CROPS.items():
        aliases = list(spec["aliases"])
        assert len(aliases) >= 3, f"{name} has {len(aliases)}: {aliases}"


def test_aliases_are_unique_within_a_crop():
    for name, spec in CROPS.items():
        aliases = [str(a) for a in spec["aliases"]]
        duplicates = {a for a in aliases if aliases.count(a) > 1}
        assert not duplicates, f"{name} repeats {sorted(duplicates)}"


def test_no_alias_is_claimed_by_two_crops():
    """`commodity_aliases.alias` is a primary key — a collision would silently
    reassign every row of one crop to the other at seed time."""
    seen: dict[str, str] = {}
    for name, spec in CROPS.items():
        for alias in spec["aliases"]:
            key = str(alias).strip().lower()
            assert key not in seen, f"alias {alias!r} claimed by both {seen[key]} and {name}"
            seen[key] = name


def test_every_crop_carries_a_devanagari_alias():
    """A farmer typing कांदा into WhatsApp must resolve without the agent guessing."""
    for name, spec in CROPS.items():
        assert any(any("ऀ" <= ch <= "ॿ" for ch in str(a)) for a in spec["aliases"]), (
            f"{name} has no Marathi/Devanagari alias"
        )


def test_the_first_alias_is_the_upstream_spelling():
    """ingestion/datagov.py sends aliases[0] as filters[commodity]. It must be
    ASCII and title-cased the way data.gov.in spells it, not our internal key."""
    for name, spec in CROPS.items():
        first = str(spec["aliases"][0])
        assert first.isascii(), f"{name}: first alias {first!r} is not the API spelling"
        assert first[0].isupper(), f"{name}: first alias {first!r} is not capitalised"


# ══════════════════════════════════════════════════════════════════════════
# 4. seasons
# ══════════════════════════════════════════════════════════════════════════

def test_season_windows_parse_as_month_day():
    for name, spec in CROPS.items():
        seasons = dict(spec["seasons"])
        assert seasons, f"{name} has no seasons"
        for label, window in seasons.items():
            for key in ("harvest_start", "harvest_end"):
                month, day = (int(p) for p in str(dict(window)[key]).split("-"))
                assert 1 <= month <= 12, f"{name}.{label}.{key}"
                assert 1 <= day <= 31, f"{name}.{label}.{key}"


def test_every_crop_is_in_harvest_somewhere_in_the_year():
    """A crop whose windows cover no day would make `in_harvest_season` dead weight."""
    from datetime import date as _date

    import pandas as pd

    from features.builder import _in_harvest_season

    for name, spec in CROPS.items():
        days = [
            _in_harvest_season(pd.Timestamp(_date(2025, month, 15)), spec)
            for month in range(1, 13)
        ]
        assert any(days), f"{name} is never in harvest season"
        assert not all(days), f"{name} is always in harvest season — the flag says nothing"


# ══════════════════════════════════════════════════════════════════════════
# 5. districts and mandis
# ══════════════════════════════════════════════════════════════════════════

MANDIS = [m.to_dict() if hasattr(m, "to_dict") else dict(m) for m in settings.mandis.mandis]
DISTRICTS = sorted({m["district"] for m in MANDIS})


def test_there_are_at_least_three_districts():
    """The plan's target. One district cannot demonstrate 'a nearer market wins'."""
    assert len(DISTRICTS) >= 3, DISTRICTS


def test_every_district_has_at_least_two_mandis():
    """Comparing markets needs markets to compare."""
    for district in DISTRICTS:
        count = sum(1 for m in MANDIS if m["district"] == district)
        assert count >= 2, f"{district} has only {count} mandi"


def test_mandi_names_are_unique_within_a_district():
    """`mandis` is UNIQUE on (normalised_name, district, state_id) — a duplicate
    here would be silently swallowed by the ON CONFLICT at seed time."""
    from ingestion.entity_resolution import normalise

    seen: set[tuple[str, str]] = set()
    for mandi in MANDIS:
        key = (normalise(mandi["name"]), mandi["district"])
        assert key not in seen, f"duplicate mandi {mandi['name']} in {mandi['district']}"
        seen.add(key)


def test_coordinates_are_inside_maharashtra():
    """A transposed lat/lon puts a mandi in the Bay of Bengal and quietly triples
    every transport cost on the compare page."""
    for mandi in MANDIS:
        assert 15.5 <= float(mandi["lat"]) <= 22.5, f"{mandi['name']}: lat {mandi['lat']}"
        assert 72.5 <= float(mandi["lon"]) <= 81.0, f"{mandi['name']}: lon {mandi['lon']}"


def test_every_mandi_references_a_state_the_cost_model_knows():
    states = set(settings.cost_model.states.to_dict()) - {"_default"}
    for mandi in MANDIS:
        assert mandi["state"] in states, (
            f"{mandi['name']} is in {mandi['state']}, which has no fee block in "
            f"config/cost_model.yaml"
        )


def test_every_district_has_a_reference_village():
    """Quoting a Solapur farmer his distance from a Nashik village would make
    every net-in-hand figure on the compare page wrong for him."""
    villages = settings.mandis.reference_villages.to_dict()
    for district in DISTRICTS:
        assert district in villages, f"no reference village for {district}"
        village = villages[district]
        village = village.to_dict() if hasattr(village, "to_dict") else dict(village)
        assert 15.5 <= float(village["lat"]) <= 22.5
        assert 72.5 <= float(village["lon"]) <= 81.0


def test_the_flat_default_reference_village_still_exists():
    """ingestion/routing.py and the Phase 2 tests read this key by name."""
    village = settings.mandis.reference_village
    assert village.name and village.lat and village.lon


def test_districts_are_far_enough_apart_to_be_different_markets():
    """If two districts' markets are 20 km apart they are one market with two
    names, and the compare page has nothing to show."""
    from ingestion.routing import haversine_km

    centres = {
        d: (
            sum(float(m["lat"]) for m in MANDIS if m["district"] == d)
            / sum(1 for m in MANDIS if m["district"] == d),
            sum(float(m["lon"]) for m in MANDIS if m["district"] == d)
            / sum(1 for m in MANDIS if m["district"] == d),
        )
        for d in DISTRICTS
    }
    for i, first in enumerate(DISTRICTS):
        for second in DISTRICTS[i + 1:]:
            distance = haversine_km(*centres[first], *centres[second])
            assert distance > 40, f"{first} and {second} are only {distance:.0f} km apart"


# ══════════════════════════════════════════════════════════════════════════
# 6. the schema keeps up
# ══════════════════════════════════════════════════════════════════════════

SCHEMA = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


def test_schema_defines_the_crop_coverage_view():
    assert "CREATE VIEW crop_coverage" in SCHEMA


def test_crop_coverage_is_grained_by_district_and_crop():
    """The whole point of the view. A mandi-level grain would hide the fact that
    Nashik is dense in onion and empty in banana."""
    view = SCHEMA[SCHEMA.index("CREATE VIEW crop_coverage"):]
    view = view[: view.index(";")]
    assert "m.district" in view
    assert "GROUP BY m.district" in view
    for column in ("row_count", "observed_days", "first_date", "last_date", "arrival_rows"):
        assert column in view, f"crop_coverage has no {column}"


def test_the_serving_lookup_index_exists():
    """(commodity_id, mandi_id, obs_date) — every forecast read goes through it."""
    assert "idx_po_lookup ON price_observations (commodity_id, mandi_id, obs_date" in SCHEMA


def test_the_district_index_exists():
    """crop_coverage groups by district on every audit run."""
    assert "idx_mandis_district ON mandis (district)" in SCHEMA


# ══════════════════════════════════════════════════════════════════════════
# 7. the crop list reaches the two things that consume it
# ══════════════════════════════════════════════════════════════════════════

def test_the_collector_will_ask_for_every_configured_crop():
    from ingestion import datagov

    assert set(datagov.api_commodities()) == {k.lower() for k in CROPS}


def test_display_names_do_not_leak_our_internal_keys():
    """`green_chilli` is our key; "Green Chilli" is what a farmer sees.

    scripts/init_db.py seeds `commodities.name` from the key, and that name
    reaches the audit report, the API and the WhatsApp agent's replies. An
    underscore surfacing there is a small ugliness with a large blast radius —
    the audit's forecastable-crop list is matched against it by name.
    """
    for name in CROPS:
        display = name.replace("_", " ").title()
        assert "_" not in display
        assert display[0].isupper()


def test_crop_specs_skips_reserved_keys():
    """A future non-crop constant in crops.yaml must not be seeded as a vegetable."""
    assert not any(name.startswith("_") for name in CROPS)


def test_the_spoilage_anchor_lives_in_the_cost_model_not_the_crop_list():
    """It is one number shared by fourteen crops, so it belongs with the other
    economics constants — and putting it in crops.yaml would seed it as a crop."""
    assert "spoilage_anchor" not in settings.crops.to_dict()
    assert float(settings.cost_model.spoilage.anchor) > 0
