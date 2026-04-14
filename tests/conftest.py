"""Shared pytest fixtures for the Stromligning integration."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def mock_entry() -> SimpleNamespace:
    """Return a lightweight config entry stand-in for unit tests."""
    return SimpleNamespace(
        entry_id="test-entry-id",
        data={"name": "Strømligning Test"},
        options={
            "aggregation": "1h",
            "company": "company-id",
            "forecasts": False,
        },
    )


@pytest.fixture
def mock_hass() -> SimpleNamespace:
    """Return a lightweight Home Assistant stand-in for unit tests."""
    return SimpleNamespace(
        data={},
        config=SimpleNamespace(latitude=55.6761, longitude=12.5683),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(return_value=True),
            async_forward_entry_unload=AsyncMock(return_value=True),
        ),
    )
