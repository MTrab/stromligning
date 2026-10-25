"""Support for Stromligning binary_sensors."""

from __future__ import annotations

import logging

from homeassistant.components import binary_sensor
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify as util_slugify

from .naming import configuration_description, device_name
from .coordinator import StromligningConfigEntry
from .base import (
    StromligningEntity,
    StromligningBinarySensorEntityDescription,
    build_price_attributes,
)
from .const import ATTR_FORECAST_DATA, ATTR_PRICES, DOMAIN

LOGGER = logging.getLogger(__name__)

BINARY_SENSORS = [
    StromligningBinarySensorEntityDescription(
        key="tomorrow_available_vat",
        entity_category=None,
        device_class=None,
        icon="mdi:calendar-end",
        value_fn=lambda stromligning: stromligning.tomorrow_available,
        entity_registry_enabled_default=True,
        translation_key="tomorrow_available_vat",
    ),
    StromligningBinarySensorEntityDescription(
        key="tomorrow_available_ex_vat",
        entity_category=None,
        device_class=None,
        icon="mdi:calendar-end",
        value_fn=lambda stromligning: stromligning.tomorrow_available,
        entity_registry_enabled_default=False,
        translation_key="tomorrow_available_ex_vat",
    ),
    StromligningBinarySensorEntityDescription(
        key="tomorrow_spotprice_vat",
        entity_category=None,
        device_class=None,
        icon="mdi:transmission-tower-import",
        value_fn=lambda stromligning: stromligning.tomorrow_available,
        entity_registry_enabled_default=True,
        translation_key="tomorrow_spotprice_vat",
    ),
    StromligningBinarySensorEntityDescription(
        key="tomorrow_spotprice_ex_vat",
        entity_category=None,
        device_class=None,
        icon="mdi:transmission-tower-import",
        value_fn=lambda stromligning: stromligning.tomorrow_available,
        entity_registry_enabled_default=False,
        translation_key="tomorrow_spotprice_ex_vat",
    ),
]


async def async_setup_entry(hass, entry: StromligningConfigEntry, async_add_devices):
    """Set up binary sensors."""
    binary_sensors = []

    for description in BINARY_SENSORS:
        entity = StromligningBinarySensor(description, hass, entry)
        LOGGER.debug(
            "Added binary_sensor with entity_id '%s'",
            entity.entity_id,
        )
        binary_sensors.append(entity)

    async_add_devices(binary_sensors)


class StromligningBinarySensor(StromligningEntity, BinarySensorEntity):
    """Representation of a Stromligning Binary_Sensor."""

    _unrecorded_attributes = frozenset({ATTR_PRICES})

    _attr_has_entity_name = True
    _attr_available = True

    def __init__(
        self,
        description: StromligningBinarySensorEntityDescription,
        hass: HomeAssistant,
        entry: StromligningConfigEntry,
    ) -> None:
        """Initialize a Stromligning Binary_Sensor."""
        super().__init__(entry.runtime_data)

        self.entity_description: StromligningBinarySensorEntityDescription = description
        self._config = entry
        self._hass = hass
        self.api = entry.runtime_data.api

        self._attr_unique_id = util_slugify(
            f"{self.entity_description.key}_{self._config.entry_id}"
        )
        self._attr_should_poll = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._config.entry_id)},
            "name": device_name(hass, entry),
            "model": configuration_description(
                self.api.get_power_provider(), self._config.options
            ),
            "manufacturer": "Strømligning",
        }

        self.entity_id = binary_sensor.ENTITY_ID_FORMAT.format(
            util_slugify(
                f"{self._config.data.get(CONF_NAME)}_{self.entity_description.key}"
            )
        )

    def handle_attributes(self) -> None:
        """Handle attributes."""
        key = self.entity_description.key
        price_attribute_map = {
            "tomorrow_available_vat": lambda price: price["price"]["total"],
            "tomorrow_available_ex_vat": lambda price: price["price"]["value"],
            "tomorrow_spotprice_vat": lambda price: price["details"]["electricity"][
                "total"
            ],
            "tomorrow_spotprice_ex_vat": lambda price: price["details"]["electricity"][
                "value"
            ],
        }

        if key in price_attribute_map:
            self._attr_extra_state_attributes = {
                "available_at": self.api.get_next_update().strftime("%H:%M:%S"),
                ATTR_FORECAST_DATA: self.api.forecast_data,
                **build_price_attributes(
                    self.api.prices_tomorrow,
                    price_attribute_map[key],
                    self.api.get_aggregation(),
                ),
            }

    @callback
    def handle_update(self) -> None:
        """Refresh the cached value and public attributes."""
        self._attr_is_on = self.entity_description.value_fn(self.api)
        self.handle_attributes()
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Subscribe only while added and populate the initial state."""
        await super().async_added_to_hass()
        self.handle_update()
