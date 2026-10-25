"""Configure Strømligning using stable product IDs."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from pystromligning import Aggregation, Stromligning
from pystromligning.exceptions import InvalidAPIResponse, TooManyRequests
from requests.exceptions import RequestException

from .api import StromligningAPI
from .const import (
    CONF_AGGREGATION,
    CONF_COMPANY,
    CONF_DEFAULT_NAME,
    CONF_FORECASTS,
    DOMAIN,
)


def configuration_identity(options: dict) -> str:
    """Identify a product, resolution, and forecast variant at HA's location."""
    return f"{options[CONF_COMPANY]}:{options.get(CONF_AGGREGATION, '1h')}:{int(options.get(CONF_FORECASTS, False))}"


def duplicate_entry(hass, options, exclude=None):
    """Include legacy entries whose unique ID was based on a display name."""
    identity = configuration_identity(options)
    return any(
        entry.entry_id != exclude and configuration_identity(entry.options) == identity
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


def schema(companies, options):
    """Keep product IDs as values even when display names are identical."""
    if not companies:
        return vol.Schema({})
    return vol.Schema(
        {
            vol.Required(
                CONF_COMPANY, default=options.get(CONF_COMPANY, vol.UNDEFINED)
            ): vol.In({company["id"]: company["name"] for company in companies}),
            vol.Required(
                CONF_AGGREGATION, default=options.get(CONF_AGGREGATION, "1h")
            ): vol.In(Aggregation.values()),
            vol.Required(
                CONF_FORECASTS, default=options.get(CONF_FORECASTS, False)
            ): bool,
        }
    )


async def discover(hass):
    """Resolve supplier and products with the blocking library in the executor."""
    api = Stromligning(False)
    await hass.async_add_executor_job(
        api.set_location, hass.config.latitude, hass.config.longitude
    )
    if not api.supplier or not api.available_companies:
        raise InvalidAPIResponse("No suppliers or products at this location")
    return api


async def validate(hass, api, options):
    """Fetch and validate current prices before saving the selected product."""
    from types import SimpleNamespace

    connector = StromligningAPI(hass, SimpleNamespace(options=options), 5, 0)
    connector._data = api
    api.set_company(options[CONF_COMPANY])
    if not api.company:
        raise InvalidAPIResponse("Selected product is unavailable")
    api.set_aggregation(options[CONF_AGGREGATION])
    api.set_forecast(options[CONF_FORECASTS])
    await connector.update_prices()


class StromligningOptionsFlow(config_entries.OptionsFlow):
    """Validate options before the registered update listener reloads the entry."""

    async def async_step_init(self, user_input: Any | None = None):
        """Show and save settings, retaining any legacy option keys."""
        errors = {}
        companies = []
        try:
            api = await discover(self.hass)
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in user_input:
                if duplicate_entry(self.hass, user_input, self.config_entry.entry_id):
                    errors["base"] = "already_configured"
                else:
                    await validate(self.hass, api, user_input)
                    if duplicate_entry(
                        self.hass, user_input, self.config_entry.entry_id
                    ):
                        errors["base"] = "already_configured"
                    else:
                        return self.async_create_entry(
                            title="", data={**self.config_entry.options, **user_input}
                        )
        except TooManyRequests:
            errors["base"] = "too_many_requests"
        except (
            InvalidAPIResponse,
            RequestException,
            TimeoutError,
            KeyError,
            IndexError,
            ValueError,
            TypeError,
        ):
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="init",
            data_schema=schema(companies, user_input or self.config_entry.options),
            errors=errors,
        )


class StromligningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure multiple distinct product/resolution/forecast combinations."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an HA-managed options flow."""
        return StromligningOptionsFlow()

    async def async_step_user(self, user_input: Any | None = None):
        """Resolve products, reject duplicates, and test current price retrieval."""
        errors = {}
        companies = []
        try:
            api = await discover(self.hass)
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in user_input:
                await self.async_set_unique_id(configuration_identity(user_input))
                self._abort_if_unique_id_configured()
                if duplicate_entry(self.hass, user_input):
                    return self.async_abort(reason="already_configured")
                await validate(self.hass, api, user_input)
                return self.async_create_entry(
                    title=CONF_DEFAULT_NAME,
                    data={CONF_NAME: CONF_DEFAULT_NAME},
                    options=user_input,
                )
        except TooManyRequests:
            errors["base"] = "too_many_requests"
        except (
            InvalidAPIResponse,
            RequestException,
            TimeoutError,
            KeyError,
            IndexError,
            ValueError,
            TypeError,
        ):
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=schema(companies, user_input or {}),
            errors=errors,
        )
