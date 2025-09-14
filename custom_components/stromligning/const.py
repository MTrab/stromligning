"""Consts used in the integration."""

# Startup banner
STARTUP = """
-------------------------------------------------------------------
Strømligning

Version: %s
This is a custom integration
If you have any issues with this you need to open an issue here:
https://github.com/mtrab/stromligning/issues
-------------------------------------------------------------------
"""

ATTR_PRICES = "prices"
ATTR_FORECAST_DATA = "forecast_data"

CONF_AGGREGATION = "aggregation"
CONF_COMPANY = "company"
CONF_DEFAULT_NAME = "Strømligning"
CONF_FORECASTS = "forecasts"

DEFAULT_TEMPLATE = "{{0.0|float(0)}}"
DOMAIN = "stromligning"

PLATFORMS = ["sensor", "binary_sensor"]

UPDATE_SIGNAL = f"{DOMAIN}_SIGNAL_UPDATE"
UPDATE_SIGNAL_NEXT = f"{DOMAIN}_SIGNAL_UPDATE_NEXT"
