"""Configure Strømligning using stable product IDs."""

import math
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from pystromligning import Aggregation
from pystromligning.exceptions import (
    InvalidAPIKey,
    InvalidAPIResponse,
    TooManyRequests,
)
from requests.exceptions import RequestException

from .api import StromligningAPI, create_client, set_electricity_price
from .const import (
    CONF_AGGREGATION,
    CONF_API_KEY,
    CONF_COMPANY,
    CONF_DEFAULT_NAME,
    CONF_ELECTRICITY_PRICE,
    CONF_FORECASTS,
    DOMAIN,
)
from .location import home_coordinates


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


def api_key_field(options):
    """Return an optional, masked API key field prefilled with the saved key."""
    return {
        vol.Optional(
            CONF_API_KEY,
            description={"suggested_value": options.get(CONF_API_KEY)},
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    }


def clean_api_key(options):
    """Strip the API key and drop it when empty, so requests stay anonymous."""
    options = dict(options)
    key = options.pop(CONF_API_KEY, None)
    if isinstance(key, str) and key.strip():
        options[CONF_API_KEY] = key.strip()
    return options


def schema(companies, options):
    """Keep product IDs as values even when display names are identical."""
    if not companies:
        return vol.Schema(api_key_field(options))
    return vol.Schema(
        {
            vol.Required(
                CONF_COMPANY, default=options.get(CONF_COMPANY, vol.UNDEFINED)
            ): vol.In({company["id"]: company["name"] for company in companies}),
            vol.Required(
                CONF_AGGREGATION, default=options.get(CONF_AGGREGATION, "1h")
            ): vol.In(Aggregation.values()),
            vol.Required(
                CONF_FORECASTS,
                default=options.get(CONF_FORECASTS, False),
            ): bool,
            **api_key_field(options),
        }
    )


async def discover(hass, options):
    """Resolve supplier and products with the blocking library in the executor."""
    api = create_client(hass, options)
    latitude, longitude = home_coordinates(hass)
    await hass.async_add_executor_job(api.set_location, latitude, longitude)
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
    set_electricity_price(api, options)
    await connector.update_prices()


def electricity_price(value):
    """Accept a finite, non-negative price including VAT."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise vol.Invalid("invalid_price")
    if not math.isfinite(value) or value < 0:
        raise vol.Invalid("invalid_price")
    return value


class FixedPriceFlow:
    """Collect the agreed price before validating a fixed-price product."""

    def _start_fixed_price(self, api, options, previous=None):
        self._price_api = api
        self._price_options = dict(options)
        if previous and previous.get(CONF_COMPANY) == options[CONF_COMPANY]:
            if CONF_ELECTRICITY_PRICE in previous:
                self._price_options[CONF_ELECTRICITY_PRICE] = previous[
                    CONF_ELECTRICITY_PRICE
                ]
        else:
            self._price_options.pop(CONF_ELECTRICITY_PRICE, None)

    def _show_fixed_price(self, errors=None):
        return self.async_show_form(
            step_id="fixed_price",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ELECTRICITY_PRICE,
                        default=self._price_options.get(
                            CONF_ELECTRICITY_PRICE, vol.UNDEFINED
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            step="any",
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="kr/kWh",
                        )
                    ),
                }
            ),
            errors=errors or {},
        )

    async def async_step_fixed_price(self, user_input=None):
        """Retain the form on invalid input or a failed price lookup."""
        errors = {}
        if user_input is not None:
            try:
                price = electricity_price(user_input[CONF_ELECTRICITY_PRICE])
            except vol.Invalid, KeyError:
                errors[CONF_ELECTRICITY_PRICE] = "invalid_price"
            else:
                self._price_options[CONF_ELECTRICITY_PRICE] = price
                try:
                    return await self._async_save(self._price_api, self._price_options)
                except InvalidAPIKey:
                    return self.async_show_form(
                        step_id=self._settings_step_id,
                        data_schema=schema(
                            self._price_api.available_companies, self._price_options
                        ),
                        errors={"base": "invalid_api_key"},
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
        return self._show_fixed_price(errors)


class StromligningOptionsFlow(FixedPriceFlow, config_entries.OptionsFlowWithReload):
    """Validate options before Home Assistant reloads the entry."""

    _settings_step_id = "init"

    async def async_step_init(self, user_input: Any | None = None):
        """Show and save settings, retaining any legacy option keys."""
        errors = {}
        companies = []
        if user_input is not None:
            user_input = clean_api_key(user_input)
        try:
            api = await discover(self.hass, user_input or self.config_entry.options)
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in user_input:
                if duplicate_entry(self.hass, user_input, self.config_entry.entry_id):
                    errors["base"] = "already_configured"
                else:
                    api.set_company(user_input[CONF_COMPANY])
                    if api.company.get("productType") == "fixed":
                        self._start_fixed_price(
                            api, user_input, self.config_entry.options
                        )
                        return await self.async_step_fixed_price()
                    return await self._async_save(api, user_input)
        except InvalidAPIKey:
            errors["base"] = "invalid_api_key"
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

    async def _async_save(self, api, options):
        """Validate and recheck duplicates before saving options."""
        await validate(self.hass, api, options)
        if duplicate_entry(self.hass, options, self.config_entry.entry_id):
            if api.company.get("productType") == "fixed":
                return self._show_fixed_price({"base": "already_configured"})
            return self.async_show_form(
                step_id="init",
                data_schema=schema(api.available_companies, options),
                errors={"base": "already_configured"},
            )
        saved = {**self.config_entry.options, **options}
        if api.company.get("productType") != "fixed":
            saved.pop(CONF_ELECTRICITY_PRICE, None)
        if CONF_API_KEY not in options:
            saved.pop(CONF_API_KEY, None)
        return self.async_create_entry(title="", data=saved)


class StromligningConfigFlow(FixedPriceFlow, config_entries.ConfigFlow, domain=DOMAIN):
    """Configure multiple distinct product/resolution/forecast combinations."""

    VERSION = 2
    _settings_step_id = "user"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an HA-managed options flow."""
        return StromligningOptionsFlow()

    async def async_step_user(self, user_input: Any | None = None):
        """Resolve products, reject duplicates, and test current price retrieval."""
        errors = {}
        companies = []
        if user_input is not None:
            user_input = clean_api_key(user_input)
        try:
            api = await discover(self.hass, user_input or {})
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in user_input:
                await self.async_set_unique_id(configuration_identity(user_input))
                self._abort_if_unique_id_configured()
                if duplicate_entry(self.hass, user_input):
                    return self.async_abort(reason="already_configured")
                api.set_company(user_input[CONF_COMPANY])
                if api.company.get("productType") == "fixed":
                    self._start_fixed_price(api, user_input)
                    return await self.async_step_fixed_price()
                return await self._async_save(api, user_input)
        except InvalidAPIKey:
            errors["base"] = "invalid_api_key"
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

    async def _async_save(self, api, options):
        """Validate prices and check for entries created during either step."""
        await validate(self.hass, api, options)
        self._abort_if_unique_id_configured()
        if duplicate_entry(self.hass, options):
            return self.async_abort(reason="already_configured")
        saved = dict(options)
        if api.company.get("productType") != "fixed":
            saved.pop(CONF_ELECTRICITY_PRICE, None)
        return self.async_create_entry(
            title=CONF_DEFAULT_NAME,
            data={CONF_NAME: CONF_DEFAULT_NAME},
            options=saved,
        )

    async def async_step_reauth(self, entry_data):
        """Ask for a new API key after the API rejected the saved one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Any | None = None):
        """Check the new key, or no key, and reload the entry with it."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            options = clean_api_key({**entry.options, **user_input})
            if CONF_API_KEY not in user_input:
                options.pop(CONF_API_KEY, None)
            try:
                api = await discover(self.hass, options)
                await validate(self.hass, api, options)
            except InvalidAPIKey:
                errors["base"] = "invalid_api_key"
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
            else:
                return self.async_update_reload_and_abort(entry, options=options)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(api_key_field({})),
            errors=errors,
        )
