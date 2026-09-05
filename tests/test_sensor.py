"""Tests for Strømligning sensor entities."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.stromligning.sensor import SENSORS, StromligningSensor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sensor_key", "expected_spotprice"),
    [
        ("forecasts_vat", 0.8),
        ("forecasts_ex_vat", 0.64),
    ],
)
async def test_forecast_attributes_include_matching_spotprice(
    sensor_key: str, expected_spotprice: float
) -> None:
    """Forecast intervals should expose the matching VAT spot price."""
    sensor = StromligningSensor.__new__(StromligningSensor)
    sensor.entity_description = next(
        description for description in SENSORS if description.key == sensor_key
    )
    sensor.api = SimpleNamespace(
        prices_forecasts=[
            {
                "date": datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
                "price": {"total": 1.3, "value": 1.04},
                "details": {"electricity": {"total": 0.8, "value": 0.64}},
            }
        ],
        prices_today=[],
        get_aggregation=lambda: "1h",
    )

    await sensor.handle_attributes()

    assert sensor.extra_state_attributes == {
        "prices": [
            {
                "price": 1.3 if sensor_key == "forecasts_vat" else 1.04,
                "spotprice": expected_spotprice,
                "start": datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
                "end": datetime(2026, 2, 25, 0, 0, tzinfo=UTC),
            }
        ]
    }
