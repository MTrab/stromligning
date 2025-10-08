"""Add support for Stromligning energy prices."""

import logging
from datetime import datetime
from random import randint

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_utc_time_change,
)
from homeassistant.loader import async_get_integration
from homeassistant.util import slugify as util_slugify
from pystromligning import Aggregation
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests

from .api import StromligningAPI
from .const import DOMAIN, PLATFORMS, STARTUP, UPDATE_SIGNAL

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Strømligning from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    integration = await async_get_integration(hass, DOMAIN)
    LOGGER.info(STARTUP, integration.version)
    rand_min = randint(5, 40)
    rand_sec = randint(0, 59)

    api = StromligningAPI(hass, entry, rand_min, rand_sec)
    hass.data[DOMAIN][entry.entry_id] = api

    forecasts = entry.options.get("forecasts", False)
    aggregation = entry.options.get("aggregation", Aggregation.HOUR)

    try:
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

            if len(api.prices_tomorrow) > 0:
                api.prices_today = api.prices_tomorrow
                api.prices_tomorrow = []
                api.tomorrow_available = False
            else:
                await api.update_prices()
                await api.prepare_data()

            async_dispatcher_send(hass, util_slugify(UPDATE_SIGNAL))

        async def new_quarter(n):  # type: ignore pylint: disable=unused-argument, invalid-name
            """Tell the sensor to update to a new quarter."""
            LOGGER.debug("New quarter, updating state")

            if len(api.prices_tomorrow) == 0 and datetime.now().hour > 13:
                LOGGER.info(
                    "Prices for tomorrow is missing - trying to fetch data from API"
                )
                await api.update_prices()
                await api.prepare_data()

            async_dispatcher_send(hass, util_slugify(UPDATE_SIGNAL))

        # Handle dataset updates
        update_tomorrow = async_track_time_change(
            hass,
            get_new_data,
            hour=13,  # LOCAL time!!
            minute=rand_min,
            second=rand_sec,
        )

        if forecasts:
            update_forecast = async_track_utc_time_change(
                hass, get_new_data, hour="/6", minute=10, second=0  # UTC time!!
            )
            api.listeners.append(update_forecast)

        if aggregation == Aggregation.MIN15:
            update_new_quarter = async_track_time_change(
                hass, new_quarter, minute="/15", second=1
            )
        else:
            update_new_quarter = async_track_time_change(
                hass, new_quarter, hour="/1", minute=0, second=1
            )

        update_new_day = async_track_time_change(
            hass, new_day, hour=0, minute=0, second=1
        )

        api.listeners.append(update_new_quarter)
        api.listeners.append(update_new_day)
        api.listeners.append(update_tomorrow)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        return True
    except TooManyRequests:
        raise ConfigEntryNotReady("Too many requests to the API within 15 minutes")
        # LOGGER.info(
        #     "You made too many requests to the API within a 15 minutes window - try again later"
        # )

        # return False
    except InvalidAPIResponse as ex:
        LOGGER.error("Unable to connect to the Stromligning API: %s", ex)
        raise ConfigEntryNotReady from ex


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    for platform in PLATFORMS:
        unload_ok = await hass.config_entries.async_forward_entry_unload(
            entry, platform
        )

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
