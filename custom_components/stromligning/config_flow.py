"""Configure Strømligning using stable product IDs."""

import math
from types import SimpleNamespace
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
    FixedPriceRequired,
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

REMOVE_API_KEY = "remove_api_key"


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


def api_key_fields(has_key: bool = False) -> dict:
    """Let users change a key without including it in the form."""
    fields = {
        vol.Optional(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
    if has_key:
        fields[vol.Optional(REMOVE_API_KEY, default=False)] = bool
    return fields


def schema(companies, options):
    """Keep product IDs as values even when display names are identical."""
    key_fields = api_key_fields(bool(options.get(CONF_API_KEY)))
    if not companies:
        return vol.Schema(key_fields)
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
            **key_fields,
        }
    )


async def discover(hass, options):
    """Resolve supplier and products with the blocking library in the executor."""
    key = options.get(CONF_API_KEY)
    if key and any(not 33 <= ord(character) <= 126 for character in key):
        raise InvalidAPIKey("The API key contains invalid characters")
    api = create_client(hass, options)
    latitude, longitude = home_coordinates(hass)
    await hass.async_add_executor_job(api.set_location, latitude, longitude)
    if not api.supplier or not api.available_companies:
        raise InvalidAPIResponse("No suppliers or products at this location")
    return api


async def validate(hass, api, options):
    """Fetch and validate current prices before saving the selected product."""
    connector = StromligningAPI(hass, SimpleNamespace(options=options), 5, 0, api)
    api.set_company(options[CONF_COMPANY])
    if not api.company:
        raise InvalidAPIResponse("Selected product is unavailable")
    api.set_aggregation(options.get(CONF_AGGREGATION, "1h"))
    api.set_forecast(options.get(CONF_FORECASTS, False))
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

    _discovered_options: dict | None = None

    @staticmethod
    def _with_api_key(user_input, previous):
        """Carry a key through discovery without exposing it in the form."""
        options = dict(user_input)
        remove_key = options.pop(REMOVE_API_KEY, False)
        new_key = options.pop(CONF_API_KEY, "").strip()
        if not remove_key and (key := new_key or previous.get(CONF_API_KEY)):
            options[CONF_API_KEY] = key
        return options

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
                        step_id=self._settings_step,
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

    _settings_step = "init"

    async def async_step_init(self, user_input: Any | None = None):
        """Show and save settings, retaining any legacy option keys."""
        errors = {}
        companies = []
        previous = (
            self.config_entry.options
            if self._discovered_options is None
            else self._discovered_options
        )
        options = (
            previous if user_input is None else self._with_api_key(user_input, previous)
        )
        try:
            api = await discover(self.hass, options)
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in options:
                if duplicate_entry(self.hass, options, self.config_entry.entry_id):
                    errors["base"] = "already_configured"
                else:
                    api.set_company(options[CONF_COMPANY])
                    if api.company.get("productType") == "fixed":
                        self._start_fixed_price(api, options, self.config_entry.options)
                        return await self.async_step_fixed_price()
                    return await self._async_save(api, options)
            self._discovered_options = options
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
            data_schema=schema(companies, {**self.config_entry.options, **options}),
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
    _settings_step = "user"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an HA-managed options flow."""
        return StromligningOptionsFlow()

    async def async_step_user(self, user_input: Any | None = None):
        """Resolve products, reject duplicates, and test current price retrieval."""
        errors = {}
        companies = []
        previous = {} if self._discovered_options is None else self._discovered_options
        options = (
            previous if user_input is None else self._with_api_key(user_input, previous)
        )
        try:
            api = await discover(self.hass, options)
            companies = api.available_companies
            if user_input is not None and CONF_COMPANY in options:
                await self.async_set_unique_id(configuration_identity(options))
                self._abort_if_unique_id_configured()
                if duplicate_entry(self.hass, options):
                    return self.async_abort(reason="already_configured")
                api.set_company(options[CONF_COMPANY])
                if api.company.get("productType") == "fixed":
                    self._start_fixed_price(api, options)
                    return await self.async_step_fixed_price()
                return await self._async_save(api, options)
            self._discovered_options = options
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
            data_schema=schema(companies, options),
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
            options = dict(entry.options)
            options.pop(CONF_API_KEY, None)
            options.update(self._with_api_key(user_input, {}))
            try:
                api = await discover(self.hass, options)
                await validate(self.hass, api, options)
            except InvalidAPIKey:
                errors["base"] = "invalid_api_key"
            except FixedPriceRequired:
                errors["base"] = "fixed_price_required"
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
            data_schema=vol.Schema(api_key_fields()),
            errors=errors,
        )
