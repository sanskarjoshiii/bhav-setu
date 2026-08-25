"""Phase A1 acceptance — the daily collector.

Run:  make check-phaseA1

No database and no API key. Every request is served by `httpx.MockTransport`, so
this suite proves the paging, the resume and the refusal-to-invent-data without
spending a single call against a public server we have already been rate-limited
by once.

The two tests that matter most:

  * `test_resume_*` — kill it halfway, re-run, it picks up. The plan's own
    acceptance step, and the reason a throttle stops being expensive.
  * `test_run_refuses_a_vacuous_result` — a collector that fetched nothing must
    fail loudly. Silence from an upstream API is indistinguishable from a quiet
    market unless something refuses to accept it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import httpx
import pandas as pd
import pytest

from core.config import settings
from core.errors import IngestionError
from ingestion import datagov
from ingestion.cleaners import CANONICAL_COLUMNS

pytestmark = pytest.mark.phaseA1

RUN_DATE = date(2026, 8, 25)


# ══════════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_credentials() -> Iterator[None]:
    """Fill the two env vars the endpoint needs. `Env` is frozen by design."""
    env = settings.env
    saved = (env.data_gov_in_api_key, env.agmarknet_resource_id)
    object.__setattr__(env, "data_gov_in_api_key", "test-key")
    object.__setattr__(env, "agmarknet_resource_id", "test-resource")
    try:
        yield
    finally:
        object.__setattr__(env, "data_gov_in_api_key", saved[0])
        object.__setattr__(env, "agmarknet_resource_id", saved[1])


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the page cache at a temp dir — tests never touch data/artifacts."""
    monkeypatch.setattr(datagov, "CACHE_DIR", tmp_path / "datagov_cache")
    return tmp_path / "datagov_cache"


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff is real in production and pointless in a test."""
    monkeypatch.setattr(datagov.time, "sleep", lambda _seconds: None)


def _record(market: str = "Lasalgaon", commodity: str = "Onion",
            modal: str = "1860", day: str = "25/08/2026") -> dict[str, str]:
    return {
        "arrival_date": day,
        "state": "Maharashtra",
        "district": "Nashik",
        "market": market,
        "commodity": commodity,
        "variety": "Red",
        "grade": "FAQ",
        "min_price": "1600",
        "max_price": "2100",
        "modal_price": modal,
        "arrivals": "820",
    }


class RecordingTransport(httpx.MockTransport):
    """A mock transport that remembers every request, so we can count calls."""

    def __init__(self, handler) -> None:
        self.requests: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(wrapped)

    @property
    def offsets(self) -> list[int]:
        return [int(r.url.params.get("offset", -1)) for r in self.requests]


def _client(handler) -> tuple[httpx.Client, RecordingTransport]:
    transport = RecordingTransport(handler)
    return httpx.Client(transport=transport), transport


def _pages_handler(pages: list[list[dict[str, Any]]]):
    """Serve `pages[offset // limit]`, or an empty page past the end."""

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        index = offset // datagov.PAGE_LIMIT
        records = pages[index] if index < len(pages) else []
        return httpx.Response(200, json={"records": records})

    return handler


# ══════════════════════════════════════════════════════════════════════════
# 1. which crops we ask for
# ══════════════════════════════════════════════════════════════════════════

def test_crop_list_comes_from_crops_yaml():
    """Adding a crop must be a config change, not a code change."""
    mapping = datagov.api_commodities()
    assert mapping, "config/crops.yaml produced no crops"
    assert set(mapping) == {k.lower() for k in settings.crops.to_dict()}


def test_api_commodity_defaults_to_the_first_alias():
    """crops.yaml writes the upstream spelling first, so that is what we filter on."""
    crops = settings.crops.to_dict()
    key = next(iter(crops))
    spec = crops[key]
    aliases = list((spec.to_dict() if hasattr(spec, "to_dict") else dict(spec))["aliases"])
    assert datagov.api_commodities()[key.lower()] == str(aliases[0])


def test_crop_filter_selects_a_subset():
    key = next(iter(settings.crops.to_dict())).lower()
    assert list(datagov.api_commodities([key])) == [key]


def test_unknown_crop_is_a_clear_error():
    with pytest.raises(IngestionError, match="unknown crop"):
        datagov.api_commodities(["dragonfruit"])


# ══════════════════════════════════════════════════════════════════════════
# 2. the page cache
# ══════════════════════════════════════════════════════════════════════════

def test_page_round_trips_through_the_cache(cache: Path):
    records = [_record(), _record(market="Pimpalgaon")]
    datagov._store_page(RUN_DATE, "onion", 0, records)
    assert datagov._load_page(RUN_DATE, "onion", 0) == records


def test_cached_pages_stop_at_the_first_hole(cache: Path):
    """Page 2 without page 1 is not two pages of history — it is a hole."""
    datagov._store_page(RUN_DATE, "onion", 0, [_record()])
    datagov._store_page(RUN_DATE, "onion", 2, [_record()])
    assert len(datagov.cached_pages(RUN_DATE, "onion")) == 1


def test_page_write_is_atomic(cache: Path):
    """Write-then-rename: a kill mid-write must not leave a page a later run trusts."""
    datagov._store_page(RUN_DATE, "onion", 0, [_record()])
    directory = datagov.cache_dir(RUN_DATE, "onion")
    assert not list(directory.glob("*.part"))
    assert (directory / "page-000.json").exists()


def test_corrupt_cache_page_is_ignored_not_trusted(cache: Path):
    path = datagov._page_path(RUN_DATE, "onion", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert datagov._load_page(RUN_DATE, "onion", 0) is None


# ══════════════════════════════════════════════════════════════════════════
# 3. paging
# ══════════════════════════════════════════════════════════════════════════

def test_pages_until_a_short_page(fake_credentials, cache: Path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 2)
    client, transport = _client(_pages_handler([
        [_record(), _record()],
        [_record(), _record()],
        [_record()],                      # short -> stop here
    ]))
    with client:
        records, pages, from_cache, used_keyword = datagov.fetch_crop(
            client, "onion", "Onion", RUN_DATE
        )
    assert (pages, from_cache, used_keyword) == (3, 0, False)
    assert len(records) == 5
    assert transport.offsets == [0, 2, 4]


def test_a_single_short_page_is_one_request(fake_credentials, cache: Path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 100)
    client, transport = _client(_pages_handler([[_record()]]))
    with client:
        _, pages, _, _ = datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    assert pages == 1
    assert len(transport.requests) == 1


def test_page_cap_stops_a_runaway(fake_credentials, cache: Path, monkeypatch):
    """A paging bug must cost us 4 requests, not 200."""
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 1)
    monkeypatch.setattr(datagov, "MAX_PAGES", 4)
    client, transport = _client(lambda r: httpx.Response(200, json={"records": [_record()]}))
    with client:
        _, pages, _, _ = datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    assert pages == 4
    assert len(transport.requests) == 4


def test_request_carries_key_filters_and_paging(fake_credentials, cache: Path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 50)
    client, transport = _client(_pages_handler([[_record()]]))
    with client:
        datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    params = transport.requests[0].url.params
    assert params["api-key"] == "test-key"
    assert params["format"] == "json"
    assert params["limit"] == "50"
    assert params["filters[commodity]"] == "Onion"
    assert params["filters[state]"] == datagov.STATE
    assert "test-resource" in str(transport.requests[0].url)


# ══════════════════════════════════════════════════════════════════════════
# 4. resume — the plan's own acceptance step
# ══════════════════════════════════════════════════════════════════════════

def test_resume_skips_pages_already_on_disk(fake_credentials, cache: Path, monkeypatch):
    """Kill it halfway, re-run: it picks up at page 1, not page 0."""
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 2)
    datagov._store_page(RUN_DATE, "onion", 0, [_record(), _record()])

    client, transport = _client(_pages_handler([
        [_record(), _record()],           # page 0 — must NOT be requested
        [_record()],                      # page 1 — short, ends the walk
    ]))
    with client:
        records, pages, from_cache, _ = datagov.fetch_crop(
            client, "onion", "Onion", RUN_DATE
        )
    assert from_cache == 1
    assert pages == 2
    assert len(records) == 3
    assert transport.offsets == [2], "page 0 was re-fetched despite being cached"


def test_resume_from_a_complete_crop_makes_no_requests(fake_credentials, cache: Path, monkeypatch):
    """A cached short page means the crop was already walked to the end."""
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    datagov._store_page(RUN_DATE, "onion", 0, [_record()])

    client, transport = _client(_pages_handler([[_record()]]))
    with client:
        records, pages, from_cache, _ = datagov.fetch_crop(
            client, "onion", "Onion", RUN_DATE
        )
    assert (pages, from_cache, len(records)) == (1, 1, 1)
    assert transport.requests == [], "a fully cached crop still hit the network"


def test_fresh_ignores_the_cache(fake_credentials, cache: Path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    datagov._store_page(RUN_DATE, "onion", 0, [_record()])

    client, transport = _client(_pages_handler([[_record()]]))
    with client:
        _, _, from_cache, _ = datagov.fetch_crop(
            client, "onion", "Onion", RUN_DATE, resume=False
        )
    assert from_cache == 0
    assert len(transport.requests) == 1


def test_each_crop_caches_separately(fake_credentials, cache: Path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    datagov._store_page(RUN_DATE, "onion", 0, [_record()])
    assert datagov.cached_pages(RUN_DATE, "tomato") == []


# ══════════════════════════════════════════════════════════════════════════
# 5. the upstream's two known misbehaviours
# ══════════════════════════════════════════════════════════════════════════

def test_empty_first_page_retries_with_keyword_filters(fake_credentials, cache: Path, monkeypatch):
    """Newer resources want filters[state.keyword]. We try once and say so."""
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        if "filters[commodity.keyword]" in request.url.params:
            return httpx.Response(200, json={"records": [_record()]})
        return httpx.Response(200, json={"records": []})

    client, transport = _client(handler)
    with client:
        records, pages, _, used_keyword = datagov.fetch_crop(
            client, "onion", "Onion", RUN_DATE
        )
    assert used_keyword is True
    assert len(records) == 1
    assert len(transport.requests) == 2


def test_transient_failure_is_retried(fake_credentials, cache: Path, no_sleep, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="upstream busy")
        return httpx.Response(200, json={"records": [_record()]})

    client, _ = _client(handler)
    with client:
        records, _, _, _ = datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    assert len(records) == 1
    assert calls["n"] == 2


def test_a_bad_api_key_fails_immediately(fake_credentials, cache: Path, no_sleep, monkeypatch):
    """No amount of backoff fixes a rejected key — fail on the first 403."""
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    client, transport = _client(lambda r: httpx.Response(403, text="forbidden"))
    with client:
        with pytest.raises(IngestionError, match="DATA_GOV_IN_API_KEY"):
            datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    assert len(transport.requests) == 1, "a rejected key was retried"


def test_persistent_failure_raises_after_the_configured_attempts(
    fake_credentials, cache: Path, no_sleep, monkeypatch
):
    monkeypatch.setattr(datagov, "PAGE_LIMIT", 10)
    monkeypatch.setattr(datagov, "ATTEMPTS", 3)
    client, transport = _client(lambda r: httpx.Response(500, text="boom"))
    with client:
        with pytest.raises(IngestionError, match="3 attempts failed"):
            datagov.fetch_crop(client, "onion", "Onion", RUN_DATE)
    assert len(transport.requests) == 3


# ══════════════════════════════════════════════════════════════════════════
# 6. parsing
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class _FakeResolution:
    entity_id: int | None
    matched: bool = True


class FakeResolver:
    """Duck-typed stand-in so parsing is testable without a database."""

    MANDIS = {"lasalgaon": 1, "pimpalgaon": 2}
    COMMODITIES = {"onion": 10, "tomato": 11}

    def resolve_commodity(self, name: str) -> _FakeResolution:
        return _FakeResolution(self.COMMODITIES.get(name.strip().lower()))

    def resolve_mandi(self, name: str, district: str = "", state: str = "") -> _FakeResolution:
        return _FakeResolution(self.MANDIS.get(name.strip().lower()))


def _to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    return datagov.records_to_frame(
        records,
        FakeResolver(),  # type: ignore[arg-type]
        columns=datagov._CFG.api_columns.to_dict(),
        date_format=datagov.DATE_FORMAT,
        units=datagov._CFG.units.to_dict(),
    )


def test_parsing_produces_the_canonical_columns():
    frame = _to_frame([_record()])
    assert list(frame.columns) == list(CANONICAL_COLUMNS)
    assert frame.iloc[0]["modal_price"] == pytest.approx(1860.0)
    assert frame.iloc[0]["mandi_id"] == 1
    assert frame.iloc[0]["commodity_id"] == 10
    assert frame.iloc[0]["obs_date"] == pd.Timestamp("2026-08-25")


def test_unresolvable_rows_are_dropped_not_guessed():
    """A market we do not know about must not become a market we invented."""
    frame = _to_frame([_record(), _record(market="Somewhere Else")])
    assert len(frame) == 1


def test_unknown_commodity_is_dropped():
    frame = _to_frame([_record(commodity="Dragonfruit")])
    assert frame.empty


def test_unparseable_date_is_dropped():
    frame = _to_frame([_record(day="not-a-date")])
    assert frame.empty


def test_a_missing_upstream_field_names_the_field_and_the_fix():
    bad = _record()
    del bad["modal_price"]
    with pytest.raises(IngestionError, match="datagov.api_columns"):
        _to_frame([bad])


def test_empty_records_produce_an_empty_frame():
    assert _to_frame([]).empty


# ══════════════════════════════════════════════════════════════════════════
# 7. anti-vacuity — the check that makes an outage look like an outage
# ══════════════════════════════════════════════════════════════════════════

def test_run_refuses_a_vacuous_result():
    """Every crop empty is an outage, not a quiet market. It must not pass silently."""
    result = datagov.CollectResult(run_date=RUN_DATE)
    result.crops.append(datagov.CropResult(crop="onion", api_commodity="Onion"))
    result.crops.append(datagov.CropResult(crop="tomato", api_commodity="Tomato"))
    with pytest.raises(IngestionError, match="we do not invent data"):
        datagov._assert_not_vacuous(result)


def test_one_row_is_enough_to_count_as_a_real_run():
    result = datagov.CollectResult(run_date=RUN_DATE)
    crop = datagov.CropResult(crop="onion", api_commodity="Onion")
    crop.rows_fetched = 1
    result.crops.append(crop)
    datagov._assert_not_vacuous(result)          # must not raise


def test_result_reports_empty_and_failed_crops_separately():
    """'No data today' and 'the request blew up' are different facts."""
    result = datagov.CollectResult(run_date=RUN_DATE)
    quiet = datagov.CropResult(crop="tomato", api_commodity="Tomato")
    broken = datagov.CropResult(crop="okra", api_commodity="Okra", error="HTTP 500")
    healthy = datagov.CropResult(crop="onion", api_commodity="Onion",
                                 rows_fetched=40, rows_written=38)
    result.crops.extend([quiet, broken, healthy])

    assert result.empty_crops == ["tomato"]
    assert result.failed_crops == ["okra"]
    assert result.rows_written == 38
    assert json.loads(json.dumps(result.to_dict()))["crops_attempted"] == 3


# ══════════════════════════════════════════════════════════════════════════
# 8. the script's own guard rail
# ══════════════════════════════════════════════════════════════════════════

def test_collector_blocks_clearly_without_credentials():
    """The error a teammate hits on a fresh checkout must say what to do."""
    import importlib.util
    import sys

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts) not in sys.path:                 # for the script's own _bootstrap
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("collect_daily", scripts / "collect_daily.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    env = settings.env
    saved = (env.data_gov_in_api_key, env.agmarknet_resource_id)
    object.__setattr__(env, "data_gov_in_api_key", "")
    object.__setattr__(env, "agmarknet_resource_id", "")
    try:
        blocker = module._require_credentials()
        assert blocker is not None
        assert "DATA_GOV_IN_API_KEY" in blocker
        assert "data.gov.in" in blocker
    finally:
        object.__setattr__(env, "data_gov_in_api_key", saved[0])
        object.__setattr__(env, "agmarknet_resource_id", saved[1])
