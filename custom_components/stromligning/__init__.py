"""Add support for Stromligning energy prices."""

import logging
from random import randint

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.loader import async_get_integration
from homeassistant.util import slugify as util_slugify

from .api import StromligningAPI
from .const import DOMAIN, PLATFORMS, STARTUP, UPDATE_SIGNAL

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energi Data Service from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    integration = await async_get_integration(hass, DOMAIN)
    LOGGER.info(STARTUP, integration.version)
    rand_min = randint(5, 40)
    rand_sec = randint(0, 59)

    api = StromligningAPI(hass, entry, rand_min, rand_sec)
    hass.data[DOMAIN][entry.entry_id] = api

    await api.set_location()
    await api.update_prices()
    await api.prepare_data()

    async def get_new_data(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Fetch new data for tomorrows prices at 13:00ish CET."""
        LOGGER.debug("Getting latest dataset")

        await api.update_prices()
        await api.prepare_data()

        async_dispatcher_send(hass, util_slugify(UPDATE_SIGNAL))

    async def new_day(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Handle data on new day."""
        LOGGER.debug("New day function called")

        async_dispatcher_send(hass, util_slugify(UPDATE_SIGNAL))

    async def new_hour(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Tell the sensor to update to a new hour."""
        LOGGER.debug("New hour, updating state")

        async_dispatcher_send(hass, util_slugify(UPDATE_SIGNAL))

    # Handle dataset updates
    update_tomorrow = async_track_time_change(
        hass,
        get_new_data,
        hour=13,  # LOCAL time!!
        minute=rand_min,
        second=rand_sec,
    )

    update_new_hour = async_track_time_change(hass, new_hour, minute=0, second=1)

    api.listeners.append(update_new_hour)
    api.listeners.append(update_tomorrow)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, PLATFORMS)

    if unload_ok:
        for unsub in hass.data[DOMAIN][entry.entry_id].listeners:
            unsub()
        hass.data[DOMAIN].pop(entry.entry_id)

        return True

    return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
