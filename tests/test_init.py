"""Tests for integration setup scheduling and rollover behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.stromligning import async_setup_entry
from custom_components.stromligning.const import DOMAIN


class FakeAPI:
    """Simple API stub used to capture setup side effects."""

    def __init__(self, hass, entry, rand_min: int, rand_sec: int) -> None:
        """Initialize the fake API."""
        self.hass = hass
        self.entry = entry
        self.rand_min = rand_min
        self.rand_sec = rand_sec
        self.prices_today = []
        self.prices_tomorrow = [{"date": "tomorrow-price"}]
        self.prices_forecasts = []
        self.forecast_data = False
        self.tomorrow_available = True
        self.listeners = []
        self.set_location_calls = 0
        self.update_prices_calls = 0
        self.prepare_data_calls = 0

    async def set_location(self) -> None:
        """Track initial setup."""
        self.set_location_calls += 1

    async def update_prices(self) -> None:
        """Track fetch attempts."""
        self.update_prices_calls += 1

    async def prepare_data(self) -> None:
        """Track data preparation calls."""
        self.prepare_data_calls += 1


@pytest.mark.asyncio
async def test_async_setup_entry_rolls_tomorrow_into_today_at_midnight(
    monkeypatch, mock_hass, mock_entry
) -> None:
    """The scheduled midnight callback should move tomorrow data into today."""
    callbacks = []
    dispatches: list[str] = []

    def track_time_change(hass, action, **kwargs):
        callbacks.append((kwargs, action))
        return lambda: None

    async def get_integration(hass, domain):
        return SimpleNamespace(version="test")

    monkeypatch.setattr(
        "custom_components.stromligning.async_get_integration",
        get_integration,
    )
    monkeypatch.setattr("custom_components.stromligning.randint", lambda start, end: 5)
    monkeypatch.setattr("custom_components.stromligning.StromligningAPI", FakeAPI)
    monkeypatch.setattr(
        "custom_components.stromligning.async_track_time_change",
        track_time_change,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.async_track_utc_time_change",
        track_time_change,
    )
    monkeypatch.setattr(
        "custom_components.stromligning.async_dispatcher_send",
        lambda hass, signal: dispatches.append(signal),
    )

    result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True
    api = mock_hass.data[DOMAIN][mock_entry.entry_id]
    assert api.set_location_calls == 1
    assert api.update_prices_calls == 1
    assert api.prepare_data_calls == 1

    midnight_callback = next(
        action
        for kwargs, action in callbacks
        if kwargs == {"hour": 0, "minute": 0, "second": 1}
    )

    await midnight_callback(None)

    assert api.prices_today == [{"date": "tomorrow-price"}]
    assert api.prices_tomorrow == []
    assert api.tomorrow_available is False
    assert mock_hass.config_entries.async_forward_entry_setups.await_count == 1
    assert dispatches
