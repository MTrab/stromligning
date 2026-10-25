"""Support for Stromligning sensors."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components import sensor
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify as util_slugify

from .coordinator import StromligningConfigEntry
from .api import StromligningAPI
from .base import (
    StromligningEntity,
    StromligningSensorEntityDescription,
    build_price_attributes,
)
from .const import ATTR_PRICES, CONF_FORECASTS, DOMAIN

LOGGER = logging.getLogger(__name__)

AtValueGetter = Callable[[StromligningAPI], object]

SENSORS = [
    StromligningSensorEntityDescription(
        key="current_price_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_current(True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="current_price_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="current_price_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_current(False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="current_price_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="spotprice_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-import",
        value_fn=lambda stromligning: stromligning.get_spot(True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="spotprice_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="spotprice_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-import",
        value_fn=lambda stromligning: stromligning.get_spot(False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="spotprice_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="electricity_tax_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:currency-eur",
        value_fn=lambda stromligning: stromligning.get_electricitytax(True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="electricity_tax_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="electricity_tax_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:currency-eur",
        value_fn=lambda stromligning: stromligning.get_electricitytax(False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="electricity_tax_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_min_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today("min", vat=True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="today_min_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_min_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today("min", vat=False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="today_min_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_max_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today("max", vat=True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="today_max_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_max_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today("max", vat=False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="today_max_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_mean_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today("mean", vat=True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="today_mean_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="today_mean_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_today(
            "mean", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="today_mean_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_min_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "min", vat=True
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="tomorrow_min_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_min_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "min", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="tomorrow_min_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_max_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "max", vat=True
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="tomorrow_max_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_max_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "max", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="tomorrow_max_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_mean_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "mean", vat=True
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="tomorrow_mean_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="tomorrow_mean_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:flash",
        value_fn=lambda stromligning: stromligning.get_specific_tomorrow(
            "mean", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="tomorrow_mean_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="next_data_refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-fast",
        value_fn=lambda stromligning: stromligning.get_next_update(),
        entity_registry_enabled_default=True,
        translation_key="next_data_refresh",
    ),
    StromligningSensorEntityDescription(
        key="net_owner",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=None,
        device_class=None,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_net_owner(),
        entity_registry_enabled_default=False,
        translation_key="net_owner",
    ),
    StromligningSensorEntityDescription(
        key="provider",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=None,
        device_class=None,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda stromligning: stromligning.get_power_provider(),
        entity_registry_enabled_default=False,
        translation_key="provider",
    ),
    StromligningSensorEntityDescription(
        key="price_resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=None,
        device_class=None,
        icon="mdi:chart-timeline-variant",
        value_fn=lambda stromligning: stromligning.get_aggregation(),
        entity_registry_enabled_default=False,
        translation_key="price_resolution",
    ),
    StromligningSensorEntityDescription(
        key="surcharge_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:plus-circle-multiple",
        value_fn=lambda stromligning: stromligning.get_surcharge(vat=True),
        entity_registry_enabled_default=True,
        translation_key="surcharge_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="surcharge_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:plus-circle-multiple",
        value_fn=lambda stromligning: stromligning.get_surcharge(vat=False),
        entity_registry_enabled_default=False,
        translation_key="surcharge_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="systemtariff_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_transmission_tariff(
            tariff="systemTariff", vat=True
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="systemtariff_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="systemtariff_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_transmission_tariff(
            tariff="systemTariff", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="systemtariff_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="nettariff_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_transmission_tariff(
            tariff="netTariff", vat=True
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="nettariff_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="nettariff_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_transmission_tariff(
            tariff="netTariff", vat=False
        ),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="nettariff_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="distribution_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_distribution(vat=True),
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
        translation_key="distribution_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="distribution_ex_vat",
        entity_category=None,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda stromligning: stromligning.get_distribution(vat=False),
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="distribution_ex_vat",
        unit_of_measurement="kr/kWh",  # type: ignore
    ),
    StromligningSensorEntityDescription(
        key="forecasts_vat",
        entity_category=None,
        state_class=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:electron-framework",
        value_fn=lambda stromligning: stromligning.get_forecasts(vat=True),
        entity_registry_enabled_default=True,
        translation_key="forecasts_vat",
    ),
    StromligningSensorEntityDescription(
        key="forecasts_ex_vat",
        entity_category=None,
        state_class=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:electron-framework",
        value_fn=lambda stromligning: stromligning.get_forecasts(vat=False),
        entity_registry_enabled_default=False,
        translation_key="forecasts_ex_vat",
    ),
    StromligningSensorEntityDescription(
        key="forecasts_spotprice_vat",
        entity_category=None,
        state_class=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:electron-framework",
        value_fn=lambda stromligning: stromligning.get_forecasts(vat=True),
        entity_registry_enabled_default=True,
        translation_key="forecasts_spotprice_vat",
    ),
    StromligningSensorEntityDescription(
        key="forecasts_spotprice_ex_vat",
        entity_category=None,
        state_class=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:electron-framework",
        value_fn=lambda stromligning: stromligning.get_forecasts(vat=False),
        entity_registry_enabled_default=False,
        translation_key="forecasts_spotprice_ex_vat",
    ),
]


async def async_setup_entry(hass, entry: StromligningConfigEntry, async_add_devices):
    """Set up sensors."""
    sensors = []

    forecasts = entry.options.get(CONF_FORECASTS, False)

    for description in SENSORS:
        if "forecast" in description.key and not forecasts:
            continue

        entity = StromligningSensor(description, hass, entry)
        LOGGER.debug(
            "Added sensor with entity_id '%s'",
            entity.entity_id,
        )
        sensors.append(entity)

    async_add_devices(sensors)


class StromligningSensor(StromligningEntity, SensorEntity):
    """Representation of a Stromligning Sensor."""

    _unrecorded_attributes = frozenset({ATTR_PRICES})

    _attr_has_entity_name = True
    _attr_available = True

    def __init__(
        self,
        description: StromligningSensorEntityDescription,
        hass: HomeAssistant,
        entry: StromligningConfigEntry,
    ) -> None:
        """Initialize a Stromligning Sensor."""
        super().__init__(entry.runtime_data)

        self.entity_description = description
        self._config = entry
        self._hass = hass
        self.api = entry.runtime_data.api

        self._attr_unique_id = util_slugify(
            f"{self.entity_description.key}_{self._config.entry_id}"
        )
        self._attr_should_poll = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._config.entry_id)},
            "name": self._config.data.get(CONF_NAME),
            "manufacturer": "Strømligning",
        }

        self._attr_native_unit_of_measurement = (
            self.entity_description.unit_of_measurement
        )

        self.entity_id = sensor.ENTITY_ID_FORMAT.format(
            util_slugify(
                f"{self._config.data.get(CONF_NAME)}_{self.entity_description.key}"
            )
        )

    def handle_attributes(self) -> None:
        """Handle attributes."""
        key = self.entity_description.key

        price_attribute_map = {
            "current_price_vat": (
                self.api.prices_today,
                lambda price: price["price"]["total"],
            ),
            "current_price_ex_vat": (
                self.api.prices_today,
                lambda price: price["price"]["value"],
            ),
            "distribution_vat": (
                self.api.prices_today,
                lambda price: price["details"]["distribution"]["total"],
            ),
            "distribution_ex_vat": (
                self.api.prices_today,
                lambda price: price["details"]["distribution"]["value"],
            ),
            "forecasts_vat": (
                self.api.prices_forecasts,
                lambda price: price["price"]["total"],
            ),
            "forecasts_ex_vat": (
                self.api.prices_forecasts,
                lambda price: price["price"]["value"],
            ),
            "forecasts_spotprice_vat": (
                self.api.prices_forecasts,
                lambda price: price["details"]["electricity"]["total"],
            ),
            "forecasts_spotprice_ex_vat": (
                self.api.prices_forecasts,
                lambda price: price["details"]["electricity"]["value"],
            ),
            "spotprice_vat": (
                self.api.prices_today,
                lambda price: price["details"]["electricity"]["total"],
            ),
            "spotprice_ex_vat": (
                self.api.prices_today,
                lambda price: price["details"]["electricity"]["value"],
            ),
        }

        at_attribute_map: dict[str, AtValueGetter] = {
            "today_min_vat": lambda api: api.get_specific_today(
                "min", date=True, vat=True
            ),
            "today_min_ex_vat": lambda api: api.get_specific_today(
                "min", date=True, vat=False
            ),
            "today_max_vat": lambda api: api.get_specific_today(
                "max", date=True, vat=True
            ),
            "today_max_ex_vat": lambda api: api.get_specific_today(
                "max", date=True, vat=False
            ),
            "tomorrow_min_vat": lambda api: api.get_specific_tomorrow(
                "min", date=True, vat=True
            ),
            "tomorrow_min_ex_vat": lambda api: api.get_specific_tomorrow(
                "min", date=True, vat=False
            ),
            "tomorrow_max_vat": lambda api: api.get_specific_tomorrow(
                "max", date=True, vat=True
            ),
            "tomorrow_max_ex_vat": lambda api: api.get_specific_tomorrow(
                "max", date=True, vat=False
            ),
        }

        if key in price_attribute_map:
            prices, value_getter = price_attribute_map[key]
            self._attr_extra_state_attributes = build_price_attributes(
                prices,
                value_getter,
                self.api.get_aggregation(),
            )
        elif key in at_attribute_map:
            self._attr_extra_state_attributes = {"at": at_attribute_map[key](self.api)}

    @callback
    def handle_update(self) -> None:
        """Refresh the cached value and public attributes."""
        self._attr_native_value = self.entity_description.value_fn(self.api)
        self.handle_attributes()
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Subscribe only while added and populate the initial state."""
        await super().async_added_to_hass()
        self.handle_update()
