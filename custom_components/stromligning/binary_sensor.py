"""Support for Stromligning binary_sensors."""

from __future__ import annotations

import logging

from homeassistant.components import binary_sensor
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import slugify as util_slugify
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests

from .api import StromligningAPI
from .base import StromligningBinarySensorEntityDescription
from .const import DOMAIN, UPDATE_SIGNAL

LOGGER = logging.getLogger(__name__)

BINARY_SENSORS = [
    StromligningBinarySensorEntityDescription(
        key="tomorrow_available",
        entity_category=None,
        device_class=None,
        icon="mdi:calendar-end",
        value_fn=lambda stromligning: stromligning.tomorrow_available,
        translation_key="tomorrow_available",
    )
]


async def async_setup_entry(hass, entry: ConfigEntry, async_add_devices):
    """Setup binary_sensors."""
    binary_sensors = []

    for binary_sensor in BINARY_SENSORS:
        entity = StromligningBinarySensor(binary_sensor, hass, entry)
        LOGGER.debug(
            "Added binary_sensor with entity_id '%s'",
            entity.entity_id,
        )
        binary_sensors.append(entity)

    async_add_devices(binary_sensors)


class StromligningBinarySensor(BinarySensorEntity):
    """Representation of a Stromligning Binary_Sensor."""

    _attr_has_entity_name = True
    _attr_available = True

    def __init__(
        self,
        description: StromligningBinarySensorEntityDescription,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize a Stromligning Binary_Sensor."""
        super().__init__()

        self.entity_description = description
        self._config = entry
        self._hass = hass
        self.api: StromligningAPI = hass.data[DOMAIN][entry.entry_id]

        self._attr_unique_id = util_slugify(
            f"{self.entity_description.key}_{self._config.entry_id}"
        )
        self._attr_should_poll = True

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._config.entry_id)},
            "name": self._config.data.get(CONF_NAME),
            "manufacturer": "Strømligning",
        }

        async_dispatcher_connect(
            self._hass,
            util_slugify(UPDATE_SIGNAL),
            self.handle_update,
        )

        self.entity_id = binary_sensor.ENTITY_ID_FORMAT.format(
            util_slugify(
                f"{self._config.data.get(CONF_NAME)}_{self.entity_description.key}"
            )
        )

    async def handle_attributes(self) -> None:
        """Handle attributes."""
        if self.entity_description.key == "tomorrow_available":
            self._attr_extra_state_attributes = {}
            if self._attr_is_on:
                price_set: list = []
                for price in self.api.prices_tomorrow:
                    price_set.append(
                        {
                            price["date"].strftime("%H:%M:%S"): (
                                price["price"]["total"]
                                if self.api.include_vat
                                else price["price"]["value"]
                            )
                        }
                    )

                self._attr_extra_state_attributes.update({"prices": price_set})
            else:
                self._attr_extra_state_attributes.update(
                    {"available_at": self.api.next_update}
                )

    async def handle_update(self) -> None:
        """Handle data update."""
        try:
            self._attr_is_on = self.entity_description.value_fn(
                self._hass.data[DOMAIN][self._config.entry_id]
            )
            LOGGER.debug("Setting value to: %s", self._attr_is_on)
            await self.handle_attributes()
            self._attr_available = True
        except TooManyRequests:
            if self._attr_available:
                LOGGER.warning(
                    "You made too many requests to the API and have been banned for 15 minutes."
                )
            self._attr_available = False
        except InvalidAPIResponse:
            if self._attr_available:
                LOGGER.error("The Stromligning API made an invalid response.")
            self._attr_available = False

    async def async_added_to_hass(self):
        await self.handle_update()
        return await super().async_added_to_hass()
