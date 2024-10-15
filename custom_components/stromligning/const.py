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

DOMAIN = "stromligning"

PLATFORMS = ["sensor", "binary_sensor"]

CONF_USE_VAT = "vat"
CONF_COMPANY = "company"
CONF_DEFAULT_NAME = "Strømligning"

UPDATE_SIGNAL = f"{DOMAIN}_SIGNAL_UPDATE"
