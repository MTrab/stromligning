"""API connector for Stromligning."""

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_utils
from homeassistant.util import slugify as util_slugify
from pystromligning import Stromligning
from pystromligning.exceptions import TooManyRequests

from .const import CONF_AGGREGATION, CONF_COMPANY, CONF_FORECASTS, UPDATE_SIGNAL_NEXT

RETRY_MINUTES = 5
MAX_RETRY_MINUTES = 60

LOGGER = logging.getLogger(__name__)


class StromligningAPI:
    """An object to store Stromligning API date."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, rand_min: int, rand_sec: int
    ) -> None:
        """Initialize the Stromligning connector object."""
        self.next_update = f"13:{rand_min}:{rand_sec}"

        self._entry = entry

        self.hass = hass

        self._data = Stromligning(False)

        self.prices_today: list = []
        self.prices_tomorrow: list = []

        self.tomorrow_available: bool = False

        self.listeners = []

        self.last_update: datetime | None = None

    async def set_location(self) -> None:
        """Set the location."""
        LOGGER.debug(
            "Setting location to %s, %s",
            self.hass.config.latitude,
            self.hass.config.longitude,
        )
        await self.hass.async_add_executor_job(
            self._data.set_location,
            self.hass.config.latitude,
            self.hass.config.longitude,
        )

        LOGGER.debug(
            "Setting company to %s",
            self._entry.options.get(CONF_COMPANY),
        )
        self._data.set_company(str(self._entry.options.get(CONF_COMPANY)))

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

    async def update_prices(self) -> None:
        """Update the price object."""
        today_midnight_utc = (
            dt_utils.as_utc(
                dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .isoformat()
            .replace("+00:00", ".000Z")
        )
        try:
            await self.hass.async_add_executor_job(
                self._data.update, today_midnight_utc
            )
            self.last_update = dt_utils.now()
        except TooManyRequests:
            LOGGER.info(
                "You made too many requests to the API within a 15 minutes window - try again later"
            )

    async def prepare_data(self) -> None:
        """Prepare the data for use in Home Assistant."""
        LOGGER.debug("Preparing data")

        today_midnight_utc = dt_utils.as_utc(
            dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        tomorrow_midnight_utc = dt_utils.as_utc(
            (dt_utils.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        day3_midnight_utc = dt_utils.as_utc(
            (dt_utils.now() + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        )

        self.prices_today = []
        self.prices_tomorrow = []
        self.prices_forecasts = []

        self.forecast_data: bool = False

        for price in self._data.prices:
            # Convert the price date to datetime first
            price_dt = datetime.fromisoformat(price["date"])

            if today_midnight_utc <= price_dt < tomorrow_midnight_utc:
                price["date"] = dt_utils.as_local(price_dt)
                self.prices_today.append(price)
            elif tomorrow_midnight_utc <= price_dt < day3_midnight_utc:
                price["date"] = dt_utils.as_local(price_dt)
                self.prices_tomorrow.append(price)
                if price.get("forecast", False):
                    self.forecast_data = True
            else:
                price["date"] = dt_utils.as_local(price_dt)
                self.prices_forecasts.append(price)

        LOGGER.debug("Found %s entries for tomorrow", len(self.prices_tomorrow))
        if len(self.prices_tomorrow) >= 23 and not self.forecast_data:
            LOGGER.debug("Prices for tomorrow are valid")
            self.tomorrow_available = True
        else:
            LOGGER.debug("Prices for tomorrow are NOT valid")
            if not self.forecast_data:
                LOGGER.debug("Clearing prices for tomorrow")
                self.prices_tomorrow = []
            self.tomorrow_available = False
        async_dispatcher_send(self.hass, util_slugify(UPDATE_SIGNAL_NEXT))

    def get_current(self, vat: bool = True) -> str | None:
        """Get the current price"""
        for price in self.prices_today:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today) == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):
                LOGGER.debug(
                    "Returning '%s' as current price",
                    (price["price"]["total"] if vat else price["price"]["value"]),
                )
                return price["price"]["total"] if vat else price["price"]["value"]

    def get_forecasts(self, vat: bool = True) -> datetime | None:
        """Get forecasts"""

        return self.last_update

    def get_spot(self, vat: bool = True, tomorrow: bool = False) -> str | None:
        """Get spotprice"""
        for price in self.prices_today if not tomorrow else self.prices_tomorrow:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today if not tomorrow else self.prices_tomorrow)
                == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):

                LOGGER.debug(
                    "Returning '%s' as current spotprice",
                    (
                        price["details"]["electricity"]["total"]
                        if vat
                        else price["details"]["electricity"]["value"]
                    ),
                )
                return (
                    price["details"]["electricity"]["total"]
                    if vat
                    else price["details"]["electricity"]["value"]
                )

    def get_electricitytax(self, vat: bool = True) -> str | None:
        """Get electricity tax"""
        for price in self.prices_today:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today) == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):

                LOGGER.debug(
                    "Returning '%s' as current electricity tax",
                    (
                        price["details"]["electricityTax"]["total"]
                        if vat
                        else price["details"]["electricityTax"]["value"]
                    ),
                )
                return (
                    price["details"]["electricityTax"]["total"]
                    if vat
                    else price["details"]["electricityTax"]["value"]
                )

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
                    if price["date"] >= dt_utils.now():
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
        """Get next API update timestamp."""
        n_update = self.next_update.split(":")

        data_refresh = dt_utils.now().replace(
            hour=int(n_update[0]),
            minute=int(n_update[1]),
            second=int(n_update[2]),
            microsecond=0,
        )

        if dt_utils.now() > data_refresh and self.tomorrow_available is False:
            data_refresh = data_refresh.replace(
                hour=dt_utils.now().hour + 1, minute=0, second=2
            )
        elif dt_utils.now().hour > 13:
            data_refresh = data_refresh + timedelta(days=1)

        return data_refresh

    def get_net_owner(self) -> str:
        """Get net operator."""
        return self._data.supplier["companyName"]

    def get_power_provider(self) -> str:
        """Get power provider."""
        return self._data.company["name"]

    def get_surcharge(self, vat: bool = True) -> float | None:
        """Get surcharge from API."""
        for price in self.prices_today:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today) == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):
                LOGGER.debug(
                    "Returning '%s' as current surcharge",
                    (
                        price["details"]["surcharge"]["total"]
                        if vat
                        else price["details"]["surcharge"]["value"]
                    ),
                )
                return (
                    price["details"]["surcharge"]["total"]
                    if vat
                    else price["details"]["surcharge"]["value"]
                )

    def get_transmission_tariff(self, tariff: str, vat: bool = True) -> float | None:
        """Get transmission tariff from API."""
        for price in self.prices_today:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today) == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):
                LOGGER.debug(
                    "Returning '%s' as current %s tariff",
                    (
                        price["details"]["transmission"][tariff]["total"]
                        if vat
                        else price["details"]["transmission"][tariff]["value"]
                    ),
                    tariff,
                )
                return (
                    price["details"]["transmission"][tariff]["total"]
                    if vat
                    else price["details"]["transmission"][tariff]["value"]
                )

    def get_distribution(self, vat: bool = True) -> float | None:
        """Get distribution from API."""
        for price in self.prices_today:
            if not price["date"].hour == dt_utils.now().hour:
                continue

            if (
                price["date"].hour == dt_utils.now().hour
                and len(self.prices_today) == 24
            ) or (
                price["date"].minute <= dt_utils.now().minute
                and (
                    (price["date"] + timedelta(minutes=15)).minute
                    > dt_utils.now().minute
                    or (price["date"] + timedelta(minutes=15)).minute == 0
                )
            ):
                LOGGER.debug(
                    "Returning '%s' as current distribution value",
                    (
                        price["details"]["distribution"]["total"]
                        if vat
                        else price["details"]["distribution"]["value"]
                    ),
                )
                return (
                    price["details"]["distribution"]["total"]
                    if vat
                    else price["details"]["distribution"]["value"]
                )
