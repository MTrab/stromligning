"""Set up the Strømligning HACS integration."""

from random import randint

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_utils

from .api import StromligningAPI
from .const import PLATFORMS
from .coordinator import StromligningConfigEntry, StromligningCoordinator


def _entry_identity(hass: HomeAssistant, entry: StromligningConfigEntry) -> str:
    """Keep existing duplicate entries separate during migration and reload."""
    from .config_flow import configuration_identity

    identity = configuration_identity(entry.options)
    if any(
        other.entry_id != entry.entry_id and other.unique_id == identity
        for other in hass.config_entries.async_entries(entry.domain)
    ):
        return f"{identity}:legacy:{entry.entry_id}"
    return identity


async def async_setup_entry(
    hass: HomeAssistant, entry: StromligningConfigEntry
) -> bool:
    """Load one entry with HA-managed retry and cleanup."""
    previous = getattr(entry, "runtime_data", None)
    if (
        previous is not None
        and previous.rate_limit_until is not None
        and dt_utils.utcnow() < previous.rate_limit_until
    ):
        raise ConfigEntryNotReady("API rate limit; waiting for the retry deadline")
    hass.config_entries.async_update_entry(
        entry, unique_id=_entry_identity(hass, entry)
    )
    api = StromligningAPI(hass, entry, randint(5, 40), randint(0, 59))
    coordinator = StromligningCoordinator(hass, entry, api)
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.close)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start()
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: StromligningConfigEntry
) -> bool:
    """Unload all platforms and stop callbacks only when unloading succeeds."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.close()
        return True
    return False


async def async_reload_entry(
    hass: HomeAssistant, entry: StromligningConfigEntry
) -> None:
    """Reload options through Home Assistant's lifecycle."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, entry: StromligningConfigEntry
) -> bool:
    """Upgrade identity while preserving entry, device, entity, data and options."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, unique_id=_entry_identity(hass, entry), version=2
        )
    return True
