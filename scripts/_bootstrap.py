"""Puts backend/ on sys.path so scripts can `from core.config import settings`."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND: Path = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.logging import configure_stdout_utf8  # noqa: E402

configure_stdout_utf8()
