"""API connector for Stromligning."""

from copy import deepcopy
from decimal import Decimal
import logging
import math
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_utils
from pystromligning import Stromligning
from pystromligning.exceptions import (
    FixedPriceRequired,
    InvalidAPIKey,
    InvalidAPIResponse,
    TooManyRequests,
)
from requests.exceptions import RequestException

from .const import (
    CONF_AGGREGATION,
    CONF_API_KEY,
    CONF_COMPANY,
    CONF_ELECTRICITY_PRICE,
    CONF_FORECASTS,
    CONF_PRODUCTION_PRICES,
    DOMAIN,
)
from .location import home_coordinates

LOGGER = logging.getLogger(__name__)


def create_client(hass: HomeAssistant, options: dict) -> Stromligning:
    """Create a library client that identifies the integration and HA version."""
    version = async_get_loaded_integration(hass, DOMAIN).version
    return Stromligning(
        False,
        api_key=options.get(CONF_API_KEY),
        user_agent=f"HomeAssistant-Stromligning/{version} HomeAssistant/{HA_VERSION}",
    )


def set_electricity_price(api: Stromligning, options: dict) -> None:
    """Convert the agreed price including 25% VAT to the API's net price."""
    price = options.get(CONF_ELECTRICITY_PRICE)
    if api.company.get("productType") != "fixed":
        price = None
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise TypeError("Electricity price must be numeric")
        if not math.isfinite(price) or price < 0:
            raise ValueError("Electricity price must be finite and non-negative")
        price = float(Decimal(str(price)) / Decimal("1.25"))
    if api.company.get("productType") == "fixed" and price is None:
        raise FixedPriceRequired("Enter the agreed price in the integration options")
    api.set_electricity_price(price)


class StromligningAPI:
    """An object to store Stromligning API date."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        rand_min: int,
        rand_sec: int,
        client: Stromligning | None = None,
    ) -> None:
        """Initialize the Stromligning connector object."""
        self.next_update = f"13:{rand_min}:{rand_sec}"

        self._entry = entry

        self.hass = hass

        self._data = client if client is not None else Stromligning(False)

        self.prices_today: list = []
        self.prices_tomorrow: list = []

        self.tomorrow_available: bool = False

        self.prices_forecasts = []
        self.forecast_data = False
        self._snapshot = []
        self.production_today: list = []
        self._production_snapshot: list = []
        self.production_retry_at: datetime | None = None
        self.scheduled_update = None

        self.last_update: datetime | None = None

    async def set_location(self) -> None:
        """Set the location."""
        latitude, longitude = home_coordinates(self.hass)
        await self.hass.async_add_executor_job(
            self._data.set_location,
            latitude,
            longitude,
        )

        LOGGER.debug(
            "Setting company to %s",
            self._entry.options.get(CONF_COMPANY),
        )
        self._data.set_company(str(self._entry.options.get(CONF_COMPANY)))
        if not self._data.company or not self._data.supplier:
            raise InvalidAPIResponse("No matching supplier or product")

        LOGGER.debug(
            "Setting aggregation to %s",
            self._entry.options.get(CONF_AGGREGATION, "1h"),
        )
        self._data.set_aggregation(self._entry.options.get(CONF_AGGREGATION, "1h"))

        LOGGER.debug(
            "Setting forecast to %s",
            self._entry.options.get(CONF_FORECASTS, False),
        )
        self._data.set_forecast(self._entry.options.get(CONF_FORECASTS, False))
        set_electricity_price(self._data, self._entry.options)

    async def update_prices(self) -> None:
        """Update the price object."""
        today_midnight_utc = (
            dt_utils.as_utc(
                dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .isoformat()
            .replace("+00:00", ".000Z")
        )
        await self.hass.async_add_executor_job(self._data.update, today_midnight_utc)
        try:
            snapshot = self._validated_snapshot(self._data.prices)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as err:
            raise InvalidAPIResponse("Invalid price dataset") from err
        if self._find_period(snapshot, dt_utils.as_utc(dt_utils.now())) is None:
            raise InvalidAPIResponse("No price for the current period")
        await self._refresh_production(today_midnight_utc)
        self._snapshot = snapshot
        await self.prepare_data()
        self.last_update = dt_utils.now()

    @property
    def production_enabled(self) -> bool:
        """Return whether sale prices for surplus production are configured."""
        return bool(self._entry.options.get(CONF_PRODUCTION_PRICES, False))

    def has_production_price_at(self, instant: datetime) -> bool:
        """Check if a cached sale price covers the supplied instant."""
        return self._find_period(self._production_snapshot, instant) is not None

    async def _refresh_production(self, start: str) -> None:
        """Keep optional sale price failures separate from consumption prices."""
        if not self.production_enabled or (
            self.production_retry_at is not None
            and dt_utils.utcnow() < self.production_retry_at
        ):
            return
        try:
            self._production_snapshot = await self._update_production(start)
        except InvalidAPIKey:
            raise
        except TooManyRequests:
            self.production_retry_at = dt_utils.utcnow() + timedelta(minutes=15)
        except InvalidAPIResponse, RequestException, TimeoutError:
            if self.production_retry_at is None:
                LOGGER.warning("Unable to retrieve valid electricity sale prices")
            self.production_retry_at = dt_utils.utcnow() + self.period_length
        else:
            self.production_retry_at = None

    async def _update_production(self, start: str) -> list:
        """Fetch and validate the current sale prices."""
        try:
            await self.hass.async_add_executor_job(self._data.update_production, start)
            snapshot = self._validated_snapshot(
                self._data.production_prices, production=True
            )
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as err:
            raise InvalidAPIResponse("Invalid production price dataset") from err
        if self._find_period(snapshot, dt_utils.as_utc(dt_utils.now())) is None:
            raise InvalidAPIResponse("No production price for the current period")
        return snapshot

    @staticmethod
    def _validated_snapshot(prices: list, *, production: bool = False) -> list:
        """Copy, normalize and validate a dataset before publishing it."""
        snapshot = deepcopy(prices)
        for price in snapshot:
            value = price["date"]
            start = datetime.fromisoformat(value) if isinstance(value, str) else value
            if start.tzinfo is None:
                raise ValueError("Naive price timestamp")
            price["date"] = dt_utils.as_local(start)
            amounts = [price["price"]]
            if not production:
                amounts.extend(
                    price["details"][key]
                    for key in (
                        "electricity",
                        "electricityTax",
                        "surcharge",
                        "distribution",
                    )
                )
                amounts.extend(
                    price["details"]["transmission"][key]
                    for key in ("systemTariff", "netTariff")
                )
            for amount in amounts:
                for key in ("value", "total"):
                    if isinstance(amount[key], bool) or not isinstance(
                        amount[key], (int, float)
                    ):
                        raise TypeError("Non-numeric price")
                    if not math.isfinite(amount[key]):
                        raise ValueError("Non-finite price")
        snapshot.sort(key=lambda price: dt_utils.as_utc(price["date"]))
        starts = [dt_utils.as_utc(price["date"]) for price in snapshot]
        if len(starts) != len(set(starts)):
            raise ValueError("Duplicate periods")
        return snapshot

    async def prepare_data(self) -> None:
        """Rebucket the last successful snapshot without mutating library data."""
        midnight = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today, tomorrow, day3 = (
            dt_utils.as_utc(midnight + timedelta(days=offset)) for offset in range(3)
        )
        self.prices_today = [
            price
            for price in self._snapshot
            if today <= dt_utils.as_utc(price["date"]) < tomorrow
        ]
        self.prices_tomorrow = [
            price
            for price in self._snapshot
            if tomorrow <= dt_utils.as_utc(price["date"]) < day3
        ]
        self.prices_forecasts = [
            price for price in self._snapshot if dt_utils.as_utc(price["date"]) >= day3
        ]
        self.production_today = [
            price
            for price in self._production_snapshot
            if today <= dt_utils.as_utc(price["date"]) < tomorrow
        ]
        self.forecast_data = any(
            price.get("forecast", False) for price in self.prices_tomorrow
        )
        interval = self.period_length
        expected = [
            tomorrow + index * interval
            for index in range((day3 - tomorrow) // interval)
        ]
        actual = [dt_utils.as_utc(price["date"]) for price in self.prices_tomorrow]
        self.tomorrow_available = actual == expected and not self.forecast_data
        if not self.tomorrow_available and not self.forecast_data:
            self.prices_tomorrow = []

    @property
    def period_length(self) -> timedelta:
        """Return the configured elapsed period length."""
        return timedelta(minutes=15 if self.get_aggregation() == "15m" else 60)

    def _find_period(self, prices: list, instant: datetime) -> dict | None:
        """Find a half-open interval in UTC, including repeated local hours."""
        return next(
            (
                price
                for price in prices
                if dt_utils.as_utc(price["date"])
                <= instant
                < dt_utils.as_utc(price["date"]) + self.period_length
            ),
            None,
        )

    def current_period(self) -> dict | None:
        """Return the current interval, never an expired matching clock hour."""
        return self._find_period(self.prices_today, dt_utils.as_utc(dt_utils.now()))

    def _current_value(self, path: tuple[str, ...], vat: bool) -> float | None:
        """Read a component from the current interval."""
        price = self.current_period()
        if price is None:
            return None
        for key in path:
            price = price[key]
        return price["total" if vat else "value"]

    def get_current(self, vat: bool = True) -> float | None:
        """Return the current total price."""
        return self._current_value(("price",), vat)

    def get_production(self, vat: bool = True) -> float | None:
        """Return the current sale price for surplus production."""
        price = self._find_period(
            self.production_today, dt_utils.as_utc(dt_utils.now())
        )
        if price is None:
            return None
        return price["price"]["total" if vat else "value"]

    def get_forecasts(self, vat: bool = True) -> datetime | None:
        """Get forecasts."""

        return self.last_update

    def get_spot(self, vat: bool = True, tomorrow: bool = False) -> float | None:
        """Return the current or corresponding tomorrow spot price."""
        if tomorrow:
            price = self._find_period(
                self.prices_tomorrow,
                dt_utils.as_utc(dt_utils.now() + timedelta(days=1)),
            )
            return (
                price["details"]["electricity"]["total" if vat else "value"]
                if price
                else None
            )
        return self._current_value(("details", "electricity"), vat)

    def get_electricitytax(self, vat: bool = True) -> float | None:
        """Return the current tax."""
        return self._current_value(("details", "electricityTax"), vat)

    def mean(self, data: list, vat: bool = True) -> float | None:
        """Calculate mean value of list."""
        val = 0
        num = 0

        for i in data:
            val += i["price"]["total"] if vat else i["price"]["value"]
            num += 1

        return val / num if num > 0 else None

    def get_specific_today(
        self,
        option_type: str,
        full_day: bool = False,
        date: bool = False,
        vat: bool = True,
    ) -> str | float | datetime | None:
        """Get today specific price and time."""
        res = {}

        try:
            if not full_day:
                dataset: list = []
                for price in self.prices_today:
                    if dt_utils.as_utc(price["date"]) >= dt_utils.as_utc(
                        dt_utils.now()
                    ):
                        dataset.append(price)
            else:
                dataset = self.prices_today

            if option_type.lower() == "min":
                res = min(dataset, key=lambda k: k["price"]["value"])
            elif option_type.lower() == "max":
                res = max(dataset, key=lambda k: k["price"]["value"])
            elif option_type.lower() == "mean":
                return self.mean(dataset, vat)

            ret = {
                "date": res["date"].strftime("%H:%M:%S"),
                "price": (res["price"]["total"] if vat else res["price"]["value"]),
            }

            return ret["date"] if date else ret["price"]
        except ValueError:
            return None

    def get_specific_tomorrow(
        self, option_type: str, date: bool = False, vat: bool = True
    ) -> str | float | datetime | None:
        """Get tomorrow specific price and time."""
        try:
            if not self.tomorrow_available:
                return None

            dataset = self.prices_tomorrow
            res = {}

            if option_type.lower() == "min":
                res = min(dataset, key=lambda k: k["price"]["value"])
            elif option_type.lower() == "max":
                res = max(dataset, key=lambda k: k["price"]["value"])
            elif option_type.lower() == "mean":
                return self.mean(dataset, vat)

            ret = {
                "date": res["date"].strftime("%H:%M:%S"),
                "price": (res["price"]["total"] if vat else res["price"]["value"]),
            }

            return ret["date"] if date else ret["price"]
        except ValueError:
            return None

    def get_next_update(self) -> datetime:
        """Return the actual scheduled API attempt."""
        if self.scheduled_update is not None:
            return dt_utils.as_local(self.scheduled_update)
        hour, minute, second = map(int, self.next_update.split(":"))
        now = dt_utils.now()
        scheduled = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        return scheduled if scheduled > now else scheduled + timedelta(days=1)

    def get_net_owner(self) -> str:
        """Get net operator."""
        return self._data.supplier["companyName"]

    def get_power_provider(self) -> str:
        """Get power provider."""
        return self._data.company["name"]

    def get_aggregation(self) -> str:
        """Get configured price aggregation."""
        return str(self._entry.options.get(CONF_AGGREGATION, "1h"))

    def get_surcharge(self, vat: bool = True) -> float | None:
        """Return the current surcharge."""
        return self._current_value(("details", "surcharge"), vat)

    def get_transmission_tariff(self, tariff: str, vat: bool = True) -> float | None:
        """Return a current transmission tariff."""
        return self._current_value(("details", "transmission", tariff), vat)

    def get_distribution(self, vat: bool = True) -> float | None:
        """Return the current distribution price."""
        return self._current_value(("details", "distribution"), vat)
