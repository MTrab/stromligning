"""Support for Stromligning sensors."""

from __future__ import annotations

import logging

from homeassistant.components import sensor
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import slugify as util_slugify
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests

from .api import StromligningAPI
from .base import StromligningSensorEntityDescription
from .const import DOMAIN, UPDATE_SIGNAL

LOGGER = logging.getLogger(__name__)

SENSORS = [
    StromligningSensorEntityDescription(
        key="current_price",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_current(),
        suggested_display_precision=2,
        translation_key="current_price",
    ),
    StromligningSensorEntityDescription(
        key="spotprice",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-import",
        value_fn=lambda stromligning: stromligning.get_spot(),
        suggested_display_precision=2,
        translation_key="spotprice",
    ),
    StromligningSensorEntityDescription(
        key="electricity_tax",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:currency-eur",
        value_fn=lambda stromligning: stromligning.get_electricitytax(),
        suggested_display_precision=2,
        translation_key="electricity_tax",
    ),
]


async def async_setup_entry(hass, entry: ConfigEntry, async_add_devices):
    """Setup sensors."""
    sensors = []

    for sensor in SENSORS:
        entity = StromligningSensor(sensor, hass, entry)
        LOGGER.debug(
            "Added sensor with entity_id '%s'",
            entity.entity_id,
        )
        sensors.append(entity)

    async_add_devices(sensors)


class StromligningSensor(SensorEntity):
    """Representation of a Stromligning Sensor."""

    _attr_has_entity_name = True
    _attr_available = True

    def __init__(
        self,
        description: StromligningSensorEntityDescription,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize a Stromligning Sensor."""
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

        self._attr_native_unit_of_measurement = "kr/kWh"

        async_dispatcher_connect(
            self._hass,
            util_slugify(UPDATE_SIGNAL),
            self.handle_update,
        )

        self.entity_id = sensor.ENTITY_ID_FORMAT.format(
            util_slugify(
                f"{self._config.data.get(CONF_NAME)}_{self.entity_description.key}"
            )
        )

    async def handle_attributes(self) -> None:
        """Handle attributes."""
        if self.entity_description.key == "current_price":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            for price in self.api.prices_today:
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

    async def handle_update(self) -> None:
        """Handle data update."""
        try:
            self._attr_native_value = self.entity_description.value_fn(
                self._hass.data[DOMAIN][self._config.entry_id]
            )
            LOGGER.debug("Setting value to: %s", self._attr_native_value)
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
