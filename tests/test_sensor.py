"""Tests for forecast sensor attributes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.stromligning.sensor import SENSORS, StromligningSensor


@pytest.mark.parametrize(
    "sensor_key,expected",
    [
        ("forecasts_vat", [1.25, 2.5, 3.75]),
        ("forecasts_ex_vat", [1.0, 2.0, 3.0]),
        ("forecasts_spotprice_vat", [-0.25, 0.0, 0.5]),
        ("forecasts_spotprice_ex_vat", [-0.2, 0.0, 0.4]),
    ],
)
@pytest.mark.parametrize("aggregation", ["1h", "15m"])
@pytest.mark.parametrize("day", [(3, 29), (10, 25)])
def test_forecast_prices(sensor_key, expected, aggregation, day, monkeypatch):
    """Keep total and spot forecasts separate across both DST transitions."""
    zone = ZoneInfo("Europe/Copenhagen")
    monkeypatch.setattr(dt_utils, "DEFAULT_TIME_ZONE", zone)
    start = datetime(2026, *day, 0, 45, tzinfo=UTC)
    interval = timedelta(minutes=15 if aggregation == "15m" else 60)
    prices = [
        {
            "date": (start + index * interval).astimezone(zone),
            "price": {"total": total * 1.25, "value": total},
            "details": {"electricity": {"total": spot * 1.25, "value": spot}},
        }
        for index, (total, spot) in enumerate(zip([1, 2, 3], [-0.2, 0, 0.4]))
    ]
    sensor = StromligningSensor.__new__(StromligningSensor)
    sensor.entity_description = next(d for d in SENSORS if d.key == sensor_key)
    sensor.api = SimpleNamespace(
        prices_forecasts=prices,
        prices_today=[],
        get_aggregation=lambda: aggregation,
    )

    sensor.handle_attributes()

    assert sensor.extra_state_attributes == {
        "prices": [
            {
                "price": value,
                "start": (start + index * interval).astimezone(zone),
                "end": (start + (index + 1) * interval).astimezone(zone),
            }
            for index, value in enumerate(expected)
        ]
    }
    for index, period in enumerate(sensor.extra_state_attributes["prices"]):
        assert period["start"].astimezone(UTC) == start + index * interval
        assert period["end"].astimezone(UTC) == start + (index + 1) * interval

    sensor.api.prices_forecasts = []
    sensor.handle_attributes()
    assert sensor.extra_state_attributes == {"prices": []}
