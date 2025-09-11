"""Config flow for setting up the integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from pystromligning import Aggregation, Stromligning
from pystromligning.exceptions import TooManyRequests

from . import async_setup_entry, async_unload_entry
from .const import (
    CONF_AGGREGATION,
    CONF_COMPANY,
    CONF_DEFAULT_NAME,
    CONF_FORECASTS,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


class StromligningOptionsFlow(config_entries.OptionsFlow):
    """Stromligning options flow handler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize Stromligning options flow."""
        self._errors = {}

    async def _do_update(
        self, *args, **kwargs  # pylint: disable=unused-argument
    ) -> None:
        """Update after settings change."""
        await async_unload_entry(self.hass, self.config_entry)
        await async_setup_entry(self.hass, self.config_entry)

    async def async_step_init(self, user_input: Any | None = None):
        """Handle the initial options flow step."""
        errors = {}

        api = self.hass.data[DOMAIN][self.config_entry.entry_id]._data

        if user_input is not None and "base" not in errors:
            LOGGER.debug("Saving settings")
            for company in api.available_companies:
                if company["name"] == user_input[CONF_COMPANY]:
                    user_input[CONF_COMPANY] = company["id"]
                    break

            async_call_later(self.hass, 2, self._do_update)
            return self.async_create_entry(
                title=self.config_entry.data.get(CONF_NAME),
                data=user_input,
                description=f"Strømligning - {self.config_entry.data.get(CONF_NAME)}",
            )

        LOGGER.debug("Showing options form")

        selected_company: str | None = None
        company_list: list = []
        for company in api.available_companies:
            if company["id"] == self.config_entry.options[CONF_COMPANY]:
                selected_company = company["name"]

            if company["name"] in company_list:
                continue

            company_list.append(company["name"])

        scheme = vol.Schema(
            {
                vol.Required(CONF_COMPANY, default=selected_company): vol.In(
                    company_list
                ),
                vol.Required(
                    CONF_AGGREGATION,
                    default=self.config_entry.options.get(CONF_AGGREGATION, "1h"),
                ): vol.In(Aggregation.values()),
                vol.Required(
                    CONF_FORECASTS,
                    default=self.config_entry.options.get(CONF_FORECASTS, False),
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=scheme, errors=errors)


class StromligningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stromligning."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> StromligningOptionsFlow:
        """Get the options flow for this handler."""
        return StromligningOptionsFlow(config_entry)

    async def async_step_user(self, user_input: Any | None = None):
        """Handle the initial config flow step."""
        errors = {}

        try:
            api = Stromligning()
            await self.hass.async_add_executor_job(
                api.set_location, self.hass.config.latitude, self.hass.config.longitude
            )
        except TooManyRequests:
            errors["base"] = "too_many_requests"

        if user_input is not None and "base" not in errors:
            await self.async_set_unique_id(f"{user_input[CONF_NAME]}_stromligning")

            for company in api.available_companies:
                if company["name"] == user_input[CONF_COMPANY]:
                    user_input[CONF_COMPANY] = company["id"]
                    break

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={"name": user_input[CONF_NAME]},
                options=user_input,
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
                vol.Required(CONF_COMPANY): vol.In(company_list),
                vol.Required(CONF_AGGREGATION): vol.In(Aggregation.values()),
                vol.Required(CONF_FORECASTS, default=False): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=scheme, errors=errors)
