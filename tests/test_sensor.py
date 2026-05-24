"""Tests for tomorrow price sensors."""

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


class TestGetTomorrowCurrent:
    """Tests for get_tomorrow_current API method."""

    def test_returns_none_when_empty(self, mock_hass, mock_entry) -> None:
        """Should return None when prices_tomorrow is empty."""
        api = _build_api(mock_hass, mock_entry, [])
        assert api.get_tomorrow_current(vat=True) is None
        assert api.get_tomorrow_current(vat=False) is None

    def test_returns_first_price_vat(self, mock_hass, mock_entry) -> None:
        """Should return the first price total when vat=True."""
        prices = [
            {
                "date": "2026-02-25T00:00:00+00:00",
                "price": {"total": 1.50, "value": 1.20},
            },
            {
                "date": "2026-02-25T01:00:00+00:00",
                "price": {"total": 1.60, "value": 1.28},
            },
        ]
        api = _build_api(mock_hass, mock_entry, [])
        api.prices_tomorrow = prices
        assert api.get_tomorrow_current(vat=True) == 1.50

    def test_returns_first_price_ex_vat(self, mock_hass, mock_entry) -> None:
        """Should return the first price value when vat=False."""
        prices = [
            {
                "date": "2026-02-25T00:00:00+00:00",
                "price": {"total": 1.50, "value": 1.20},
            },
        ]
        api = _build_api(mock_hass, mock_entry, [])
        api.prices_tomorrow = prices
        assert api.get_tomorrow_current(vat=False) == 1.20


class TestGetTomorrowSpot:
    """Tests for get_tomorrow_spot API method."""

    def test_returns_none_when_empty(self, mock_hass, mock_entry) -> None:
        """Should return None when prices_tomorrow is empty."""
        api = _build_api(mock_hass, mock_entry, [])
        assert api.get_tomorrow_spot(vat=True) is None
        assert api.get_tomorrow_spot(vat=False) is None

    def test_returns_first_spot_vat(self, mock_hass, mock_entry) -> None:
        """Should return the first spot price total when vat=True."""
        prices = [
            {
                "date": "2026-02-25T00:00:00+00:00",
                "price": {"total": 1.50, "value": 1.20},
                "details": {
                    "electricity": {"total": 0.80, "value": 0.64},
                },
            },
        ]
        api = _build_api(mock_hass, mock_entry, [])
        api.prices_tomorrow = prices
        assert api.get_tomorrow_spot(vat=True) == 0.80

    def test_returns_first_spot_ex_vat(self, mock_hass, mock_entry) -> None:
        """Should return the first spot price value when vat=False."""
        prices = [
            {
                "date": "2026-02-25T00:00:00+00:00",
                "price": {"total": 1.50, "value": 1.20},
                "details": {
                    "electricity": {"total": 0.80, "value": 0.64},
                },
            },
        ]
        api = _build_api(mock_hass, mock_entry, [])
        api.prices_tomorrow = prices
        assert api.get_tomorrow_spot(vat=False) == 0.64


@pytest.mark.asyncio
async def test_prepare_data_populates_tomorrow_with_confirmed_prices(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """Tomorrow prices should be populated when confirmed (non-forecast)."""
    fixed_now = datetime(2026, 2, 24, 14, 0, tzinfo=UTC)
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
            "price": {"total": 1.0 + hour, "value": 0.8 + hour * 0.1},
            "details": {
                "electricity": {"total": 0.5 + hour * 0.05, "value": 0.4 + hour * 0.04},
            },
        }
        for hour in range(24)
    ]
    api = _build_api(mock_hass, mock_entry, prices)

    await api.prepare_data()

    assert len(api.prices_tomorrow) == 24
    assert api.tomorrow_available is True
    assert api.forecast_data is False
    assert api.get_tomorrow_current(vat=True) == 1.0
    assert api.get_tomorrow_current(vat=False) == 0.8
    assert api.get_tomorrow_spot(vat=True) == 0.5
    assert api.get_tomorrow_spot(vat=False) == 0.4


@pytest.mark.asyncio
async def test_prepare_data_keeps_tomorrow_forecast_prices(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """Tomorrow forecast prices should be kept but tomorrow_available stays False."""
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
            "price": {"total": 1.0 + hour, "value": 0.8 + hour * 0.1},
            "details": {
                "electricity": {"total": 0.5 + hour * 0.05, "value": 0.4 + hour * 0.04},
            },
            "forecast": True,
        }
        for hour in range(24)
    ]
    api = _build_api(mock_hass, mock_entry, prices)

    await api.prepare_data()

    assert len(api.prices_tomorrow) == 24
    assert api.tomorrow_available is False
    assert api.forecast_data is True
    assert api.get_tomorrow_current(vat=True) == 1.0
    assert api.get_tomorrow_spot(vat=True) == 0.5
