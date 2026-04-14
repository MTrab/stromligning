"""Tests for Stromligning API data preparation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.stromligning.api import StromligningAPI


def _build_api(mock_hass, mock_entry, prices: list[dict]) -> StromligningAPI:
    """Create a partially initialized API object for focused unit tests."""
    api = StromligningAPI.__new__(StromligningAPI)
    api.hass = mock_hass
    api._entry = mock_entry
    api._data = SimpleNamespace(prices=prices)
    api.prices_today = []
    api.prices_tomorrow = []
    api.prices_forecasts = []
    api.forecast_data = False
    api.tomorrow_available = False
    api.listeners = []
    api.last_update = None
    return api


@pytest.mark.asyncio
async def test_prepare_data_splits_prices_into_today_tomorrow_and_forecasts(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """Prepared price lists should be bucketed by day boundaries."""
    fixed_now = datetime(2026, 2, 24, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.now",
        lambda: fixed_now,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.as_local",
        lambda value: value,
    )
    sent_signals: list[str] = []
    monkeypatch.setattr(
        "custom_components.stromligning.api.async_dispatcher_send",
        lambda hass, signal: sent_signals.append(signal),
    )

    prices = [
        {"date": "2026-02-24T00:00:00+00:00", "price": {"total": 1.0}},
        {"date": "2026-02-24T23:00:00+00:00", "price": {"total": 1.1}},
        {
            "date": "2026-02-25T00:00:00+00:00",
            "price": {"total": 1.2},
            "forecast": True,
        },
        {
            "date": "2026-02-25T23:00:00+00:00",
            "price": {"total": 1.3},
            "forecast": True,
        },
        {"date": "2026-02-26T00:00:00+00:00", "price": {"total": 1.4}},
    ]
    api = _build_api(mock_hass, mock_entry, prices)

    await api.prepare_data()

    assert [price["date"] for price in api.prices_today] == [
        datetime(2026, 2, 24, 0, 0, tzinfo=UTC),
        datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
    ]
    assert [price["date"] for price in api.prices_tomorrow] == [
        datetime(2026, 2, 25, 0, 0, tzinfo=UTC),
        datetime(2026, 2, 25, 23, 0, tzinfo=UTC),
    ]
    assert [price["date"] for price in api.prices_forecasts] == [
        datetime(2026, 2, 26, 0, 0, tzinfo=UTC)
    ]
    assert api.forecast_data is True
    assert api.tomorrow_available is False
    assert sent_signals


@pytest.mark.asyncio
async def test_prepare_data_marks_tomorrow_available_with_full_non_forecast_dataset(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """Tomorrow prices should stay populated when enough non-forecast entries exist."""
    fixed_now = datetime(2026, 2, 24, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.now",
        lambda: fixed_now,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.as_local",
        lambda value: value,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.api.async_dispatcher_send",
        lambda hass, signal: None,
    )

    prices = [
        {
            "date": f"2026-02-25T{hour:02d}:00:00+00:00",
            "price": {"total": 1.0 + hour},
        }
        for hour in range(24)
    ]
    api = _build_api(mock_hass, mock_entry, prices)

    await api.prepare_data()

    assert len(api.prices_tomorrow) == 24
    assert api.forecast_data is False
    assert api.tomorrow_available is True


@pytest.mark.asyncio
async def test_prepare_data_clears_incomplete_tomorrow_without_forecasts(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """Incomplete tomorrow data should be cleared when it is not forecast data."""
    fixed_now = datetime(2026, 2, 24, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.now",
        lambda: fixed_now,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.api.dt_utils.as_local",
        lambda value: value,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.api.async_dispatcher_send",
        lambda hass, signal: None,
    )

    prices = [
        {"date": "2026-02-25T00:00:00+00:00", "price": {"total": 1.0}},
        {"date": "2026-02-25T01:00:00+00:00", "price": {"total": 1.1}},
    ]
    api = _build_api(mock_hass, mock_entry, prices)

    await api.prepare_data()

    assert api.prices_tomorrow == []
    assert api.forecast_data is False
    assert api.tomorrow_available is False
