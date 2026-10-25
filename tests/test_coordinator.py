"""Exercise serialized fetches, retries and local callbacks using real HA runtime."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from pystromligning.exceptions import TooManyRequests

from custom_components.stromligning.api import StromligningAPI
from custom_components.stromligning.coordinator import StromligningCoordinator


@pytest_asyncio.fixture
async def runtime(tmp_path, mock_entry):
    """Build a runtime with actual HA event-loop scheduling."""
    hass = HomeAssistant(str(tmp_path))
    mock_entry.async_on_unload = Mock()
    mock_entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    api = StromligningAPI(hass, mock_entry, 12, 34)
    api.set_location = AsyncMock()
    api.update_prices = AsyncMock()
    coordinator = StromligningCoordinator(hass, mock_entry, api)
    yield hass, coordinator, api
    coordinator.close()
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_first_failure_and_recovery(runtime):
    """First refresh fails explicitly and a later success updates status."""
    hass, coordinator, api = runtime
    api.update_prices.side_effect = TooManyRequests
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_config_entry_first_refresh()
    assert not coordinator.last_update_success
    api.update_prices.side_effect = None
    coordinator.rate_limit_until = None
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.last_update_success
    api.set_location.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_boundaries_do_not_fetch_and_cleanup(runtime):
    """Local updates notify subscribers without API calls; close prevents callbacks."""
    hass, coordinator, api = runtime
    await coordinator.async_refresh()
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    coordinator.start()
    listener.reset_mock()
    await coordinator._local_update(None)
    await coordinator._local_update(None)
    api.update_prices.assert_awaited_once()
    assert listener.call_count == 2
    coordinator.close()
    unsubscribe()
    await coordinator._local_update(None)
    await coordinator._fetch(None)
    assert listener.call_count == 2
    assert coordinator._api_unsub is None
    assert coordinator._local_unsub is None
    api.update_prices.assert_awaited_once()


@pytest.mark.asyncio
async def test_unload_while_fetch_running(runtime):
    """Completing an executor request after close cannot schedule another request."""
    hass, coordinator, api = runtime
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def fetch():
        entered.set()
        await finish.wait()

    api.update_prices.side_effect = fetch
    task = asyncio.create_task(coordinator._fetch(None))
    await entered.wait()
    coordinator.close()
    finish.set()
    await task
    assert coordinator._api_unsub is None


@pytest.mark.asyncio
async def test_fetch_and_rollover_are_serialized(runtime):
    """A local rollover waits for an in-flight fetch and uses its completed data."""
    hass, coordinator, api = runtime
    entered = asyncio.Event()
    finish = asyncio.Event()
    order = []

    async def fetch():
        entered.set()
        await finish.wait()
        order.append("fetch")

    async def prepare():
        order.append("local")

    api.update_prices.side_effect = fetch
    api.prepare_data = AsyncMock(side_effect=prepare)
    task = asyncio.create_task(coordinator._fetch(None))
    await entered.wait()
    local = asyncio.create_task(coordinator._local_update(None))
    await asyncio.sleep(0)
    assert order == []
    finish.set()
    await asyncio.gather(task, local)
    assert order == ["fetch", "local"]
    api.update_prices.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregation,minute", [("1h", 0), ("15m", 45)])
async def test_retry_deadline_matches_display(
    runtime, monkeypatch, aggregation, minute
):
    """Missing prices retry at actual boundaries, including across midnight."""
    hass, coordinator, api = runtime
    now = datetime(2026, 2, 24, 23, 30, 2, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.stromligning.coordinator.dt_utils.now", lambda: now
    )
    monkeypatch.setattr(
        "custom_components.stromligning.coordinator.dt_utils.as_local",
        lambda value: value,
    )
    api._entry.options["aggregation"] = aggregation
    coordinator.start()
    deadline = api.get_next_update()
    assert deadline.minute == minute
    assert deadline.second == 1
    assert deadline.day == (25 if aggregation == "1h" else 24)
    coordinator._retry_at = now + timedelta(minutes=15)
    assert coordinator._next_deadline() >= coordinator._retry_at
