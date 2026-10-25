"""Resolve the home location, respecting YAML-defined home zones."""

import voluptuous as vol
from homeassistant.const import (
    ATTR_EDITABLE,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from pystromligning.exceptions import InvalidAPIResponse


@callback
def home_coordinates(hass: HomeAssistant) -> tuple[float, float]:
    """Use a YAML home zone when explicitly marked as non-editable by HA."""
    home = hass.states.get("zone.home")
    if home is None or home.attributes.get(ATTR_EDITABLE) is not False:
        return hass.config.latitude, hass.config.longitude

    if home.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        raise InvalidAPIResponse("The YAML-defined home zone is unavailable")
    try:
        return (
            cv.latitude(home.attributes[ATTR_LATITUDE]),
            cv.longitude(home.attributes[ATTR_LONGITUDE]),
        )
    except (KeyError, vol.Invalid) as err:
        raise InvalidAPIResponse(
            "The YAML-defined home zone has invalid coordinates"
        ) from err
