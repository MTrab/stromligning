"""Support for Stromligning sensors."""

from __future__ import annotations

import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
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
from homeassistant.util import dt as dt_utils
from homeassistant.util import slugify as util_slugify
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests

from .api import StromligningAPI
from .base import StromligningSensorEntityDescription, get_next_midnight
from .const import ATTR_PRICES, CONF_FORECASTS, DOMAIN, UPDATE_SIGNAL_NEXT

LOGGER = logging.getLogger(__name__)

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
        update_signal=UPDATE_SIGNAL_NEXT,
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
        entity_registry_enabled_default=True,
        translation_key="forecasts_ex_vat",
    ),
]


async def async_setup_entry(hass, entry: ConfigEntry, async_add_devices):
    """Setup sensors."""
    sensors = []

    forecasts = entry.options.get(CONF_FORECASTS, False)

    for sensor in SENSORS:
        if "forecast" in sensor.key and not forecasts:
            continue

        entity = StromligningSensor(sensor, hass, entry)
        LOGGER.debug(
            "Added sensor with entity_id '%s'",
            entity.entity_id,
        )
        sensors.append(entity)

    async_add_devices(sensors)


class StromligningSensor(SensorEntity):
    """Representation of a Stromligning Sensor."""

    _unrecorded_attributes = frozenset({ATTR_PRICES})

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

        self._attr_native_unit_of_measurement = (
            self.entity_description.unit_of_measurement
        )

        async_dispatcher_connect(
            self._hass,
            util_slugify(self.entity_description.update_signal),
            self.handle_update,
        )

        self.entity_id = sensor.ENTITY_ID_FORMAT.format(
            util_slugify(
                f"{self._config.data.get(CONF_NAME)}_{self.entity_description.key}"
            )
        )

    async def handle_attributes(self) -> None:
        """Handle attributes."""
        if self.entity_description.key == "current_price_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["price"]["total"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)

            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})
        elif self.entity_description.key == "current_price_ex_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["price"]["value"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)

            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})
        elif self.entity_description.key == "distribution_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["details"]["distribution"]["total"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)

            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})
        elif self.entity_description.key == "distribution_ex_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["details"]["distribution"]["value"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)

            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})
        elif self.entity_description.key == "today_min_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_today("min", date=True, vat=True)}
            )
        elif self.entity_description.key == "today_min_ex_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_today("min", date=True, vat=False)}
            )
        elif self.entity_description.key == "today_max_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_today("max", date=True, vat=True)}
            )
        elif self.entity_description.key == "today_max_ex_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_today("max", date=True, vat=False)}
            )
        elif self.entity_description.key == "tomorrow_min_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_tomorrow("min", date=True, vat=True)}
            )
        elif self.entity_description.key == "tomorrow_min_ex_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_tomorrow("min", date=True, vat=False)}
            )
        elif self.entity_description.key == "tomorrow_max_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_tomorrow("max", date=True, vat=True)}
            )
        elif self.entity_description.key == "tomorrow_max_ex_vat":
            self._attr_extra_state_attributes = {}
            self._attr_extra_state_attributes.update(
                {"at": self.api.get_specific_tomorrow("max", date=True, vat=False)}
            )
        elif (
            self.entity_description.key == "forecasts_vat"
            or self.entity_description.key == "forecasts_ex_vat"
        ):
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_forecasts:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": (
                            price["price"]["total"]
                            if self.entity_description.key == "forecasts_vat"
                            else price["price"]["value"]
                        ),
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)

            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})

        elif self.entity_description.key == "spotprice_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["details"]["electricity"]["total"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)
            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})

        elif self.entity_description.key == "spotprice_ex_vat":
            self._attr_extra_state_attributes = {}
            price_set: list = []
            pset = {}
            for price in self.api.prices_today:
                if "start" in pset:
                    pset.update({"end": price["date"]})
                    price_set.append(pset)
                    pset = {}

                pset.update(
                    {
                        "price": price["details"]["electricity"]["value"],
                        "start": price["date"],
                    }
                )
            pset.update({"end": get_next_midnight()})
            price_set.append(pset)
            self._attr_extra_state_attributes.update({ATTR_PRICES: price_set})

    async def handle_update(self) -> None:
        """Handle data update."""
        try:
            self._attr_native_value = self.entity_description.value_fn(  # type: ignore
                self._hass.data[DOMAIN][self._config.entry_id]
            )

            LOGGER.debug(
                "Setting value for '%s' to: %s",
                self.entity_id,
                self._attr_native_value,
            )
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
