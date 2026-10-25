"""Regression coverage for DST, incomplete periods and atomic snapshots."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_utils
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests

from custom_components.stromligning.api import StromligningAPI
from custom_components.stromligning.base import build_price_attributes

ZONE = ZoneInfo("Europe/Copenhagen")


def price_record(start, value=0, forecast=False):
    """Build a complete library price record."""
    amount = {"value": value, "total": value * 1.25}
    return {
        "date": start.isoformat(),
        "price": amount.copy(),
        "forecast": forecast,
        "details": {
            **{
                key: amount.copy()
                for key in (
                    "electricity",
                    "electricityTax",
                    "distribution",
                    "surcharge",
                )
            },
            "transmission": {
                key: amount.copy() for key in ("netTariff", "systemTariff")
            },
        },
    }


def day_records(day, aggregation, forecast=False):
    """Generate elapsed intervals for the actual local day."""
    start = day.astimezone(UTC)
    end = (day + timedelta(days=1)).astimezone(UTC)
    interval = timedelta(minutes=15 if aggregation == "15m" else 60)
    return [
        price_record(start + index * interval, index - 4, forecast)
        for index in range((end - start) // interval)
    ]


@pytest.fixture
def api(mock_hass, mock_entry, monkeypatch):
    """Provide a real API facade with isolated synchronous I/O."""
    monkeypatch.setattr(dt_utils, "DEFAULT_TIME_ZONE", ZONE)
    connector = StromligningAPI(mock_hass, mock_entry, 12, 34)
    connector._data = SimpleNamespace(prices=[], update=Mock())

    async def executor(function, *args):
        return function(*args)

    mock_hass.async_add_executor_job = AsyncMock(side_effect=executor)
    return connector


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "day,count",
    [
        (datetime(2026, 3, 29, tzinfo=ZONE), 23),
        (datetime(2026, 10, 25, tzinfo=ZONE), 25),
        (datetime(2026, 2, 24, tzinfo=ZONE), 24),
    ],
)
@pytest.mark.parametrize("aggregation", ["1h", "15m"])
async def test_every_period_and_tomorrow_completeness(
    api, monkeypatch, day, count, aggregation
):
    """Select every elapsed period, including both occurrences of the repeated hour."""
    api._entry.options["aggregation"] = aggregation
    previous = day - timedelta(days=1)
    raw = day_records(previous, aggregation) + day_records(day, aggregation)
    api._data.prices = raw
    before = deepcopy(raw)
    monkeypatch.setattr(dt_utils, "now", lambda: previous)
    await api.update_prices()
    assert api.tomorrow_available
    assert len(api.prices_tomorrow) == count * (4 if aggregation == "15m" else 1)
    await api.prepare_data()
    assert raw == before
    for record in day_records(day, aggregation):
        start = datetime.fromisoformat(record["date"])
        for offset in (timedelta(), api.period_length - timedelta(microseconds=1)):
            instant = (start + offset).astimezone(ZONE)
            monkeypatch.setattr(dt_utils, "now", lambda: instant)
            await api.prepare_data()
            assert api.get_current() == record["price"]["total"]
            assert api.get_spot(False) == record["price"]["value"]
            assert api.get_electricitytax() == api.get_current()
            assert api.get_distribution() == api.get_current()
            assert api.get_surcharge() == api.get_current()
            assert api.get_transmission_tariff("netTariff") == api.get_current()
    assert api._data.update.call_count == 1
    attributes = build_price_attributes(
        api.prices_today, lambda item: item["price"]["total"], aggregation
    )
    for item in attributes["prices"]:
        assert (
            item["end"].astimezone(UTC) - item["start"].astimezone(UTC)
            == api.period_length
        )
        assert set(item) == {"price", "start", "end"}


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregation", ["1h", "15m"])
@pytest.mark.parametrize("damage", ["gap", "duplicate", "forecast"])
async def test_incomplete_tomorrow(api, monkeypatch, aggregation, damage):
    """Reject gaps and duplicates and distinguish forecasts from official data."""
    today = datetime(2026, 2, 24, tzinfo=ZONE)
    monkeypatch.setattr(dt_utils, "now", lambda: today)
    api._entry.options["aggregation"] = aggregation
    tomorrow = day_records(today + timedelta(days=1), aggregation, damage == "forecast")
    if damage == "gap":
        tomorrow.pop(12)
    if damage == "duplicate":
        tomorrow[12] = deepcopy(tomorrow[11])
    api._data.prices = day_records(today, aggregation) + tomorrow
    if damage == "duplicate":
        with pytest.raises(InvalidAPIResponse):
            await api.update_prices()
        return
    await api.update_prices()
    assert not api.tomorrow_available
    assert bool(api.prices_tomorrow) == (damage == "forecast")
    assert api.get_current() is not None


@pytest.mark.asyncio
async def test_failure_preserves_snapshot_and_expired_price_is_none(api, monkeypatch):
    """Only success advances the timestamp and stale data cannot match a clock hour."""
    now = datetime(2026, 2, 24, 23, tzinfo=ZONE)
    monkeypatch.setattr(dt_utils, "now", lambda: now)
    api._data.prices = day_records(now.replace(hour=0), "1h")
    await api.update_prices()
    last_update = api.last_update
    api._data.update.side_effect = TooManyRequests
    with pytest.raises(TooManyRequests):
        await api.update_prices()
    assert api.last_update == last_update
    assert api.get_current() is not None
    now += timedelta(hours=1)
    assert api.get_current() is None
    await api.prepare_data()
    assert not api.prices_today
    assert not api.forecast_data
    assert api.get_next_update().date() == now.date()


@pytest.mark.asyncio
async def test_rest_of_day_excludes_started_period(api, monkeypatch):
    """The minimum remains a future-start minimum, not the whole-day minimum."""
    now = datetime(2026, 2, 24, 12, 30, tzinfo=ZONE)
    monkeypatch.setattr(dt_utils, "now", lambda: now)
    api._data.prices = day_records(now.replace(hour=0, minute=0), "1h")
    await api.update_prices()
    assert api.get_specific_today("min", date=True) == "13:00:00"
    assert api.get_specific_today("min", full_day=True, vat=False) == -4


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["naive", "missing", "nan", "string", "empty"])
async def test_invalid_response_is_atomic(api, monkeypatch, damage):
    """Malformed responses cannot replace the last successful data or timestamp."""
    now = datetime(2026, 2, 24, 12, tzinfo=ZONE)
    monkeypatch.setattr(dt_utils, "now", lambda: now)
    api._data.prices = day_records(now.replace(hour=0), "1h")
    await api.update_prices()
    snapshot = deepcopy(api.prices_today)
    previous = api.last_update
    if damage == "naive":
        api._data.prices[0]["date"] = "2026-02-24T00:00:00"
    elif damage == "missing":
        del api._data.prices[0]["details"]
    elif damage == "nan":
        api._data.prices[0]["price"]["value"] = float("nan")
    elif damage == "string":
        api._data.prices[0]["price"]["value"] = "0"
    else:
        api._data.prices = []
    with pytest.raises(InvalidAPIResponse):
        await api.update_prices()
    assert api.prices_today == snapshot
    assert api.last_update == previous


@pytest.mark.asyncio
async def test_repeated_datetime_input_and_forecast_rollover(api, monkeypatch):
    """Datetime input is repeatable and yesterday's forecast flag cannot leak."""
    now = datetime(2026, 2, 24, 23, tzinfo=ZONE)
    monkeypatch.setattr(dt_utils, "now", lambda: now)
    midnight = now.replace(hour=0)
    api._data.prices = day_records(midnight, "1h") + day_records(
        midnight + timedelta(days=1), "1h", True
    )
    for price in api._data.prices:
        price["date"] = datetime.fromisoformat(price["date"])
    original = deepcopy(api._data.prices)
    await api.update_prices()
    await api.update_prices()
    assert api._data.prices == original
    assert api.forecast_data
    now += timedelta(hours=1)
    await api.prepare_data()
    assert api.get_current() == -5
    assert not api.forecast_data
    assert not api.tomorrow_available
    assert api.prices_tomorrow == []
