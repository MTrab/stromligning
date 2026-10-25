"""Public lifecycle and registry compatibility tests using a real HA instance."""

import asyncio
from pathlib import Path
from threading import Barrier
from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from homeassistant import config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_utils
from pystromligning.exceptions import TooManyRequests

from custom_components.stromligning.const import DOMAIN
from test_periods import day_records


@pytest_asyncio.fixture
async def integration_hass(tmp_path):
    """Start a real HA config-entry manager with isolated storage."""
    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components",
        target_is_directory=True,
    )
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config.latitude = 55.6761
    hass.config.longitude = 12.5683
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    hass.config.skip_pip = True
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    yield hass
    await hass.async_stop()
    await hass.async_block_till_done()


@pytest.fixture
def library(monkeypatch):
    """Mock only the external synchronous API, retaining real integration behavior."""
    calls = Mock()

    def location(client, latitude, longitude):
        calls.location(latitude, longitude)
        client.supplier = {"id": "grid", "companyName": "Grid", "priceArea": "DK2"}
        client.available_companies = [
            {"id": "product", "name": "Provider - Product"},
            {"id": "other", "name": "Provider - Product"},
        ]

    def update(client, start):
        calls.update()
        midnight = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        client.prices = day_records(midnight, client.aggregation)

    monkeypatch.setattr("pystromligning.Stromligning.set_location", location)
    monkeypatch.setattr("pystromligning.Stromligning.update", update)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("yaml_home", [False, True])
async def test_home_zone_coordinates_across_flows_and_setup(
    integration_hass, library, yaml_home
):
    """Only a YAML home override changes coordinates in every lookup path."""
    from homeassistant.setup import async_setup_component

    hass = integration_hass
    config = {"zone": []}
    if yaml_home:
        config["zone"] = [{"name": "Home", "latitude": 56.0, "longitude": 8.0}]
    assert await async_setup_component(hass, "zone", config)
    home = hass.states.get("zone.home")
    assert home.attributes["editable"] is not yaml_home
    expected = (56.0, 8.0) if yaml_home else (55.6761, 12.5683)

    options = {"company": "product", "aggregation": "1h", "forecasts": False}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=options
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert library.location.call_count == 2
    assert all(call.args == expected for call in library.location.call_args_list)

    library.location.reset_mock()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    library.location.assert_called_once_with(*expected)


@pytest.mark.asyncio
async def test_home_zone_setup_finishes_before_concurrent_lookups(
    integration_hass, library, monkeypatch
):
    """Concurrent config flows wait for zone setup before looking up suppliers."""
    from homeassistant.components import zone
    from homeassistant.setup import async_setup_component

    hass = integration_hass
    started = asyncio.Event()
    release = asyncio.Event()
    flows_waiting = asyncio.Event()
    original_setup = zone.async_setup
    original_dependencies = config_entries.async_process_deps_reqs
    waiting = 0

    async def delayed_setup(hass, config):
        started.set()
        await release.wait()
        return await original_setup(hass, config)

    async def process_dependencies(hass, config, integration):
        nonlocal waiting
        if integration.domain == DOMAIN:
            waiting += 1
            if waiting == 2:
                flows_waiting.set()
        return await original_dependencies(hass, config, integration)

    monkeypatch.setattr(zone, "async_setup", delayed_setup)
    monkeypatch.setattr(config_entries, "async_process_deps_reqs", process_dependencies)
    setup_task = asyncio.create_task(
        async_setup_component(
            hass,
            "zone",
            {"zone": [{"name": "Home", "latitude": 56.0, "longitude": 8.0}]},
        )
    )
    try:
        async with asyncio.timeout(10):
            await started.wait()
            flows = [
                asyncio.create_task(
                    hass.config_entries.flow.async_init(
                        DOMAIN, context={"source": "user"}
                    )
                )
                for _ in range(2)
            ]
            await flows_waiting.wait()
            assert all(not flow.done() for flow in flows)
            library.location.assert_not_called()
            release.set()
            assert await setup_task
            results = await asyncio.gather(*flows)
        assert all(result["type"] == "form" for result in results)
        assert library.location.call_count == 2
        assert all(call.args == (56.0, 8.0) for call in library.location.call_args_list)
    finally:
        release.set()
        await setup_task


@pytest.mark.asyncio
@pytest.mark.parametrize("editable", [True, None])
async def test_home_zone_without_yaml_marker_uses_config(integration_hass, editable):
    """Different coordinates alone do not identify a YAML-defined home zone."""
    from custom_components.stromligning.location import home_coordinates

    hass = integration_hass
    attrs = {"latitude": 56.0, "longitude": 8.0}
    if editable is not None:
        attrs["editable"] = editable
    hass.states.async_set("zone.home", "0", attrs)
    assert home_coordinates(hass) == (55.6761, 12.5683)
    hass.states.async_remove("zone.home")
    assert home_coordinates(hass) == (55.6761, 12.5683)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,coordinates",
    [
        ("unavailable", {"latitude": 56.0, "longitude": 8.0}),
        ("unknown", {"latitude": 56.0, "longitude": 8.0}),
        ("0", {"latitude": 56.0}),
        ("0", {"latitude": 91.0, "longitude": 8.0}),
        ("0", {"latitude": 56.0, "longitude": "invalid"}),
        ("0", {"latitude": float("nan"), "longitude": 8.0}),
    ],
)
async def test_invalid_yaml_home_returns_flow_error(
    integration_hass, library, state, coordinates
):
    """An invalid explicit override fails without an API call or silent fallback."""
    from homeassistant.setup import async_setup_component

    hass = integration_hass
    assert await async_setup_component(hass, "zone", {"zone": []})
    hass.states.async_set("zone.home", state, {"editable": False, **coordinates})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    library.location.assert_not_called()


def legacy_entry(company="product", forecasts=False):
    """Build an existing version-one config entry including its historical name."""
    return config_entries.ConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        source="user",
        title="My existing prices",
        unique_id="My existing prices_stromligning",
        data={"name": "My existing prices"},
        options={
            "name": "My existing prices",
            "company": company,
            "aggregation": "1h",
            "forecasts": forecasts,
        },
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )


async def add_entry(hass, entry):
    """Set up through HA's public entry manager."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        await hass.config_entries.async_add(entry)
    else:
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.asyncio
async def test_upgrade_preserves_registered_identity_and_reload(
    integration_hass, library
):
    """Migrate an existing entry without replacing renamed or disabled entities."""
    hass = integration_hass
    entry = legacy_entry()
    with patch.object(
        hass.config_entries, "async_setup", AsyncMock(return_value=False)
    ):
        await hass.config_entries.async_add(entry)
    registry = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="My existing prices",
    )
    unique_id = f"current_price_vat_{entry.entry_id}".lower()
    registered = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="my_saved_price",
    )
    registry.async_update_entity(registered.entity_id, name="User renamed price")
    disabled = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"current_price_ex_vat_{entry.entry_id}".lower(),
        config_entry=entry,
        device_id=device.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    await add_entry(hass, entry)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.unique_id == "product:1h:0"
    assert entry.data == {"name": "My existing prices"}
    assert entry.options["name"] == "My existing prices"
    state = hass.states.get(registered.entity_id)
    assert state is not None and state.state not in ("unknown", "unavailable")
    assert state.attributes["friendly_name"] == "User renamed price"
    assert set(state.attributes["prices"][0]) == {"price", "start", "end"}
    original_ids = set(registry.entities)
    for _ in range(2):
        coordinator = entry.runtime_data
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert coordinator._closed
        assert not coordinator._listeners
        assert coordinator._api_unsub is None
        assert coordinator._local_unsub is None
        assert set(registry.entities) == original_ids
        assert registry.async_get(registered.entity_id).device_id == device.id
        assert (
            registry.async_get(disabled.entity_id).disabled_by
            is er.RegistryEntryDisabler.USER
        )
    assert library.update.call_count == 3
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(registered.entity_id).state == "unavailable"


@pytest.mark.asyncio
async def test_setup_failure_then_success(integration_hass, library):
    """HA retries initial API failure instead of loading empty entities."""
    library.update.side_effect = TooManyRequests
    entry = await add_entry(integration_hass, legacy_entry())
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY
    assert entry.runtime_data._closed
    library.update.side_effect = None
    entry.runtime_data.rate_limit_until = dt_utils.utcnow()
    assert await integration_hass.config_entries.async_reload(entry.entry_id)
    await integration_hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_update_failure_retains_current_and_recovers(integration_hass, library):
    """A missing tomorrow or failed fetch does not invalidate a usable current price."""
    hass = integration_hass
    entry = await add_entry(hass, legacy_entry())
    coordinator = entry.runtime_data
    last_update = coordinator.api.last_update
    library.update.side_effect = TooManyRequests
    await coordinator._fetch(None)
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert coordinator.api.last_update == last_update
    states = [
        state
        for state in hass.states.async_all("sensor")
        if "current_price_vat" in state.entity_id
    ]
    assert len(states) == 1 and states[0].state != "unavailable"
    library.update.side_effect = None
    coordinator.rate_limit_until = dt_utils.utcnow()
    await coordinator._fetch(None)
    assert coordinator.last_update_success


@pytest.mark.asyncio
async def test_unload_uses_all_platform_results(integration_hass, library):
    """A failed platform unload leaves the runtime active for HA to retry."""
    from custom_components.stromligning import async_unload_entry

    hass = integration_hass
    entry = await add_entry(hass, legacy_entry())
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ) as unload:
        assert not await async_unload_entry(hass, entry)
    unload.assert_awaited_once()
    assert not entry.runtime_data._closed


@pytest.mark.asyncio
async def test_config_flow_product_ids_and_duplicates(integration_hass, library):
    """Equal display names retain distinct IDs, and exact variants cannot duplicate."""
    hass = integration_hass
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert "name" not in fields
    assert fields["company"].container == {
        "product": "Provider - Product",
        "other": "Provider - Product",
    }
    options = {"company": "product", "aggregation": "15m", "forecasts": True}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], options)
    assert result["type"] == "create_entry"
    entry = result["result"]
    assert entry.data == {"name": "Strømligning"}
    assert entry.options == options
    await hass.async_block_till_done()
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=options
    )
    assert duplicate["type"] == "abort"
    assert duplicate["reason"] == "already_configured"
    distinct = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={**options, "company": "other"}
    )
    assert distinct["type"] == "create_entry"
    await hass.async_block_till_done()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,error",
    [
        (TooManyRequests, "too_many_requests"),
        (TimeoutError, "cannot_connect"),
        (ValueError, "cannot_connect"),
        (IndexError, "cannot_connect"),
    ],
)
async def test_flow_lookup_error_and_recovery(
    integration_hass, library, failure, error
):
    """Lookup errors return an editable form and a later attempt can succeed."""
    hass = integration_hass
    library.location.side_effect = failure
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["errors"] == {"base": error}
    library.location.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert not result["errors"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"company": "product", "aggregation": "1h", "forecasts": False},
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,error",
    [(TooManyRequests, "too_many_requests"), (TimeoutError, "cannot_connect")],
)
async def test_flow_price_validation_failure(integration_hass, library, failure, error):
    """Creating an entry requires current usable prices, not just a product list."""
    hass = integration_hass
    library.update.side_effect = failure
    options = {"company": "product", "aggregation": "1h", "forecasts": False}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=options
    )
    assert result["errors"] == {"base": error}
    assert not hass.config_entries.async_entries(DOMAIN)
    library.update.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], options)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_options_preserve_name_and_reload_once(integration_hass, library):
    """Saving validated IDs reloads once and retains user names and legacy keys."""
    hass = integration_hass
    entry = await add_entry(hass, legacy_entry())
    old_runtime = entry.runtime_data
    initial_calls = library.update.call_count
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"company": "other", "aggregation": "15m", "forecasts": True}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["name"] == "My existing prices"
    assert entry.data["name"] == "My existing prices"
    assert entry.unique_id == "other:15m:1"
    assert old_runtime._closed
    assert not old_runtime._listeners
    assert library.update.call_count == initial_calls + 2
    assert len(entry.update_listeners) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,error",
    [(TooManyRequests, "too_many_requests"), (TimeoutError, "cannot_connect")],
)
async def test_options_error_recovery(integration_hass, library, failure, error):
    """Failed validation leaves the active configuration intact."""
    hass = integration_hass
    entry = await add_entry(hass, legacy_entry())
    old_options = dict(entry.options)
    library.update.side_effect = failure
    result = await hass.config_entries.options.async_init(
        entry.entry_id,
        data={"company": "other", "aggregation": "1h", "forecasts": False},
    )
    assert result["errors"] == {"base": error}
    assert entry.options == old_options
    library.update.side_effect = None
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"company": "other", "aggregation": "1h", "forecasts": False}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_legacy_duplicate_configuration_is_not_removed(integration_hass, library):
    """Existing duplicate entries migrate without merging devices or entity IDs."""
    hass = integration_hass
    first = await add_entry(hass, legacy_entry())
    second = await add_entry(hass, legacy_entry())
    assert first.entry_id != second.entry_id
    assert second.unique_id == f"product:1h:0:legacy:{second.entry_id}"
    assert first.state is second.state is config_entries.ConfigEntryState.LOADED
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=dict(first.options)
    )
    assert result["reason"] == "already_configured"
    result = await hass.config_entries.options.async_init(
        second.entry_id, data=dict(first.options)
    )
    assert result["errors"] == {"base": "already_configured"}


@pytest.mark.asyncio
async def test_unmigrated_entry_duplicate(integration_hass, library):
    """An unloaded version-one entry participates in duplicate detection."""
    hass = integration_hass
    entry = legacy_entry()
    with patch.object(
        hass.config_entries, "async_setup", AsyncMock(return_value=False)
    ):
        await hass.config_entries.async_add(entry)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=dict(entry.options)
    )
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_empty_lookup_and_missing_product(integration_hass, library, monkeypatch):
    """Empty location results can be retried and a disappeared product cannot save."""
    hass = integration_hass
    with patch("pystromligning.Stromligning.set_location"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with patch("pystromligning.Stromligning.set_company"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"company": "product", "aggregation": "1h", "forecasts": False},
        )
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_concurrent_options_do_not_create_duplicate(
    integration_hass, library, monkeypatch
):
    """Validation finishing concurrently cannot save the same configuration twice."""
    from pystromligning import Stromligning

    hass = integration_hass
    first = await add_entry(hass, legacy_entry())
    second = await add_entry(hass, legacy_entry("other"))
    original = Stromligning.set_location

    def location(client, latitude, longitude):
        original(client, latitude, longitude)
        client.available_companies.append({"id": "target", "name": "Target"})

    monkeypatch.setattr(Stromligning, "set_location", location)
    barrier = Barrier(2)
    initial_calls = library.update.call_count

    def wait_for_other_validation():
        if library.update.call_count <= initial_calls + 2:
            barrier.wait(timeout=10)

    library.update.side_effect = wait_for_other_validation
    options = {"company": "target", "aggregation": "1h", "forecasts": False}
    results = await asyncio.gather(
        hass.config_entries.options.async_init(first.entry_id, data=options),
        hass.config_entries.options.async_init(second.entry_id, data=options),
    )
    assert sorted(result["type"] for result in results) == ["create_entry", "form"]
    rejected = next(result for result in results if result["type"] == "form")
    assert rejected["errors"] == {"base": "already_configured"}
    await hass.async_block_till_done()
    assert sum(entry.options["company"] == "target" for entry in (first, second)) == 1


@pytest.mark.asyncio
async def test_setup_rate_limit_guard_and_newer_version(integration_hass, library):
    """HA setup retries respect the cooldown and unsupported entry versions fail."""
    from custom_components.stromligning import async_migrate_entry, async_setup_entry
    from homeassistant.exceptions import ConfigEntryNotReady

    hass = integration_hass
    library.update.side_effect = TooManyRequests
    entry = await add_entry(hass, legacy_entry())
    calls = library.update.call_count
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)
    assert library.update.call_count == calls
    hass.config_entries.async_update_entry(entry, version=3)
    assert not await async_migrate_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.parametrize("forecast_tomorrow", [False, True])
async def test_public_tomorrow_and_forecast_attributes(
    integration_hass, library, monkeypatch, forecast_tomorrow
):
    """Preserve public price intervals, at, available_at and forecast_data."""
    from datetime import timedelta
    from pystromligning import Stromligning

    original = Stromligning.update

    def update(client, start):
        original(client, start)
        midnight = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        client.prices.extend(
            day_records(
                midnight + timedelta(days=1), client.aggregation, forecast_tomorrow
            )
        )
        client.prices.extend(
            day_records(midnight + timedelta(days=2), client.aggregation, True)
        )

    monkeypatch.setattr(Stromligning, "update", update)
    hass = integration_hass
    entry = await add_entry(hass, legacy_entry(forecasts=True))
    binary = hass.states.get("binary_sensor.my_existing_prices_tomorrow_available_vat")
    assert binary.state == ("off" if forecast_tomorrow else "on")
    assert binary.attributes["forecast_data"] is forecast_tomorrow
    assert binary.attributes[
        "available_at"
    ] == entry.runtime_data.api.get_next_update().strftime("%H:%M:%S")
    assert binary.attributes["prices"][0]["price"] == -5
    assert set(binary.attributes["prices"][0]) == {"price", "start", "end"}
    forecast = hass.states.get("sensor.my_existing_prices_forecasts_vat")
    assert forecast.attributes["prices"][0]["price"] == -5
    assert set(forecast.attributes["prices"][0]) == {"price", "start", "end"}
    minimum = hass.states.get("sensor.my_existing_prices_tomorrow_min_vat")
    assert minimum.attributes["at"] == (None if forecast_tomorrow else "00:00:00")
    assert minimum.state == ("unknown" if forecast_tomorrow else "-5.0")
    refresh = hass.states.get("sensor.my_existing_prices_next_data_refresh")
    assert (
        dt_utils.parse_datetime(refresh.state)
        == entry.runtime_data.api.get_next_update()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("forecasts", [False, True])
async def test_spot_forecast_setup(integration_hass, library, forecasts):
    """Create spot forecasts only when enabled, with the existing VAT defaults."""
    hass = integration_hass
    entry = await add_entry(hass, legacy_entry(forecasts=forecasts))
    registry = er.async_get(hass)
    for suffix, disabled in [
        ("vat", None),
        ("ex_vat", er.RegistryEntryDisabler.INTEGRATION),
    ]:
        entity_id = f"sensor.my_existing_prices_forecasts_spotprice_{suffix}"
        registered = registry.async_get(entity_id)
        if not forecasts:
            assert registered is None
            assert hass.states.get(entity_id) is None
            continue
        assert (
            registered.unique_id
            == f"forecasts_spotprice_{suffix}_{entry.entry_id}".lower()
        )
        assert registered.disabled_by is disabled
    if forecasts:
        state = hass.states.get("sensor.my_existing_prices_forecasts_spotprice_vat")
        assert dt_utils.parse_datetime(
            state.state
        ) == entry.runtime_data.api.last_update.replace(microsecond=0)
        assert state.attributes["prices"] == []
    library.update.assert_called_once()


@pytest.mark.asyncio
async def test_spot_forecasts_during_fetch_and_rollover(
    integration_hass, library, monkeypatch
):
    """Publish both VAT variants from a completed fetch before a local rollover."""
    from datetime import timedelta
    from pystromligning import Stromligning

    hass = integration_hass
    original = Stromligning.update
    spot = 0.4

    def update(client, start):
        original(client, start)
        midnight = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        records = day_records(midnight + timedelta(days=2), client.aggregation, True)
        for record in records:
            record["details"]["electricity"] = {"value": spot, "total": spot * 1.25}
        client.prices.extend(records)

    monkeypatch.setattr(Stromligning, "update", update)
    entry = legacy_entry(forecasts=True)
    with patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)):
        await hass.config_entries.async_add(entry)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"forecasts_spotprice_ex_vat_{entry.entry_id}".lower(),
        config_entry=entry,
        suggested_object_id="export_forecast",
        disabled_by=None,
    )
    await add_entry(hass, entry)
    coordinator = entry.runtime_data
    vat_id = "sensor.my_existing_prices_forecasts_spotprice_vat"
    ex_id = "sensor.export_forecast"
    assert hass.states.get(vat_id).attributes["prices"][0]["price"] == 0.5
    assert hass.states.get(ex_id).attributes["prices"][0]["price"] == 0.4

    entered = asyncio.Event()
    release = asyncio.Event()
    original_fetch = coordinator.api.update_prices

    async def delayed_fetch():
        entered.set()
        await release.wait()
        await original_fetch()

    monkeypatch.setattr(coordinator.api, "update_prices", delayed_fetch)
    spot = -0.2
    fetch = asyncio.create_task(coordinator._fetch(None))
    local = None
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            local = asyncio.create_task(coordinator._local_update(None))
            await asyncio.sleep(0)
            assert not local.done()
            assert hass.states.get(vat_id).attributes["prices"][0]["price"] == 0.5
            assert hass.states.get(ex_id).attributes["prices"][0]["price"] == 0.4
            release.set()
            await asyncio.gather(fetch, local)
    finally:
        release.set()
        await asyncio.gather(fetch, *([local] if local else []))
    assert hass.states.get(vat_id).attributes["prices"][0]["price"] == -0.25
    assert hass.states.get(ex_id).attributes["prices"][0]["price"] == -0.2
    total = hass.states.get("sensor.my_existing_prices_forecasts_vat")
    assert total.attributes["prices"][0]["price"] == -5
    assert set(total.attributes["prices"][0]) == {"price", "start", "end"}
    assert library.update.call_count == 2
