"""Shared pytest options.

`--provider` lets the forecast contract suite be pointed at a real provider:

    pytest tests/test_phaseA0_port.py --provider baseline
    pytest tests/test_phaseA0_port.py --provider lightgbm

Swap day runs that second line against this same, unmodified file.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--provider",
        action="store",
        default=None,
        help="also run the forecast contract suite against this configured provider",
    )


@pytest.fixture(scope="session")
def provider_name(request: pytest.FixtureRequest) -> str | None:
    """The provider named with --provider, or None."""
    return request.config.getoption("--provider")
