"""Describe a configured electricity agreement consistently in Home Assistant."""

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_NAME
from homeassistant.helpers import device_registry as dr

from .const import CONF_AGGREGATION, CONF_DEFAULT_NAME, CONF_FORECASTS, DOMAIN


def configuration_description(product_name: str, options: Mapping[str, Any]) -> str:
    """Describe the agreement, price interval, and forecast setting."""
    aggregation = options.get(CONF_AGGREGATION, "1h")
    forecasts = "enabled" if options.get(CONF_FORECASTS, False) else "disabled"
    return f"{product_name} ({aggregation}, forecasts {forecasts})"


def device_name(hass, entry) -> str | None:
    """Preserve every registered device name, including the old default name."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    if device is not None:
        return device.name
    return entry.data.get(CONF_NAME, CONF_DEFAULT_NAME)
