"""Phase 0 acceptance: the skeleton exists, config loads, Postgres and Redis answer."""

from __future__ import annotations

import pytest

from core.config import settings
from core.db import ping

pytestmark = pytest.mark.phase0

REQUIRED_DIRS: tuple[str, ...] = (
    "config",
    "data/raw",
    "data/manual",
    "data/artifacts",
    "db",
    "backend/core",
    "backend/ingestion",
    "backend/features",
    "backend/ml",
    "backend/economics",
    "backend/decision",
    "backend/transparency",
    "backend/bot/locales",
    "backend/backtest",
    "backend/api/routers",
    "backend/tests",
    "scripts",
    "frontend/app",
    "frontend/components",
    "frontend/lib",
)

REQUIRED_FILES: tuple[str, ...] = (
    "docker-compose.yml",
    ".env.example",
    ".gitignore",
    "Makefile",
    "db/schema.sql",
    "backend/requirements.txt",
    "data/manual/festivals.csv",
    "data/manual/shock_events.csv",
    "config/app.yaml",
    "config/mandis.yaml",
    "config/crops.yaml",
    "config/cost_model.yaml",
    "config/model.yaml",
    "config/sources.yaml",
    "config/decision.yaml",
)


def test_directory_tree_exists() -> None:
    missing = [d for d in REQUIRED_DIRS if not settings.path(*d.split("/")).is_dir()]
    assert not missing, f"missing directories: {missing}"


def test_required_files_exist() -> None:
    missing = [f for f in REQUIRED_FILES if not settings.path(*f.split("/")).is_file()]
    assert not missing, f"missing files: {missing}"


def test_config_loads() -> None:
    assert settings.app.horizons == [1, 3, 7, 15]
    assert settings.app.quantiles["p50"] == 0.50
    assert len(settings.mandis.mandis) == 5
    assert settings.crops.onion.max_hold_days == 20


def test_config_is_frozen() -> None:
    from core.errors import ConfigError

    with pytest.raises(ConfigError):
        settings.app.horizons = [1]  # type: ignore[misc]


def test_postgres_answers() -> None:
    assert ping() is True


def test_redis_answers() -> None:
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(settings.env.redis_url, socket_connect_timeout=3)
    assert client.ping() is True
