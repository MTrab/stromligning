"""Config flow for setting up the integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from pystromligning import Stromligning

from .const import CONF_COMPANY, CONF_DEFAULT_NAME, CONF_USE_VAT, DOMAIN

LOGGER = logging.getLogger(__name__)


class StromligningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stromligning."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: Any | None = None):
        """Handle the initial config flow step."""
        errors = {}

        api = Stromligning()
        await self.hass.async_add_executor_job(
            api.set_location, self.hass.config.latitude, self.hass.config.longitude
        )

        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_NAME]}_stromligning")

            for company in api.available_companies:
                if company["name"] == user_input[CONF_COMPANY]:
                    user_input[CONF_COMPANY] = company["id"]
                    break

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
                description=f"Strømligning - {user_input[CONF_NAME]}",
            )

        LOGGER.debug("Showing configuration form")

        company_list: list = []
        for company in api.available_companies:
            if company["name"] in company_list:
                continue
            company_list.append(company["name"])

        scheme = vol.Schema(
            {
                vol.Required(CONF_NAME, default=CONF_DEFAULT_NAME): str,
                vol.Required(CONF_USE_VAT, default=True): bool,
                vol.Required(CONF_COMPANY): vol.In(company_list),
            }
        )

        return self.async_show_form(step_id="user", data_schema=scheme, errors=errors)
