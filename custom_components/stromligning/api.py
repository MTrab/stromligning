"""API connector for Stromligning."""

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_utils
from pystromligning import Stromligning
from pystromligning.exceptions import TooManyRequests

from .const import CONF_COMPANY

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

        self._data = Stromligning()

        self.prices_today: list = []
        self.prices_tomorrow: list = []

        self.tomorrow_available: bool = False

        self.listeners = []

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
        self._data.set_company(self._entry.options.get(CONF_COMPANY))

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
        except TooManyRequests:
            LOGGER.info(
                "You made too many requests to the API within a 15 minutes window - try again later"
            )

    async def prepare_data(self) -> None:
        """Prepare the data for use in Home Assistant."""
        LOGGER.debug("Preparing data")

        today_midnight_utc = (
            dt_utils.as_utc(
                dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .isoformat()
            .replace("+00:00", ".000Z")
        )

        tomorrow_midnight_utc = (
            dt_utils.as_utc(
                (dt_utils.now() + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            )
            .isoformat()
            .replace("+00:00", ".000Z")
        )

        self.prices_today = []
        self.prices_tomorrow = []

        for price in self._data.prices:
            if (
                price["date"] >= today_midnight_utc
                and price["date"] < tomorrow_midnight_utc
            ):
                price["date"] = dt_utils.as_local(datetime.fromisoformat(price["date"]))
                self.prices_today.append(price)
            elif price["date"] >= tomorrow_midnight_utc:
                price["date"] = dt_utils.as_local(datetime.fromisoformat(price["date"]))
                self.prices_tomorrow.append(price)

        LOGGER.debug("Found %s entries for tomorrow", len(self.prices_tomorrow))
        if len(self.prices_tomorrow) == 24:
            LOGGER.debug("Prices for tomorrow are valid")
            self.tomorrow_available = True
        else:
            LOGGER.debug("Prices for tomorrow are NOT valid")
            self.prices_tomorrow = []
            self.tomorrow_available = False

    def get_current(self, vat: bool = True) -> str:
        """Get the current price"""
        for price in self.prices_today:
            if price["date"].hour == dt_utils.now().hour:
                LOGGER.debug(
                    "Returning '%s' as current price",
                    (price["price"]["total"] if vat else price["price"]["value"]),
                )
                return price["price"]["total"] if vat else price["price"]["value"]

    def get_spot(self, vat: bool = True) -> str:
        """Get spotprice"""
        for price in self.prices_today:
            if price["date"].hour == dt_utils.now().hour:
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

    def get_electricitytax(self, vat: bool = True) -> str:
        """Get electricity tax"""
        for price in self.prices_today:
            if price["date"].hour == dt_utils.now().hour:
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

    def mean(self, data: list, vat: bool = True) -> float:
        """Calculate mean value of list."""
        val = 0
        num = 0

        for i in data:
            val += i["price"]["total"] if vat else i["price"]["value"]
            num += 1

        return val / num

    def get_specific_today(
        self,
        option_type: str,
        full_day: bool = False,
        date: bool = False,
        vat: bool = True,
    ) -> str | datetime:
        """Get today specific price and time."""
        res = None

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

    def get_specific_tomorrow(
        self, option_type: str, date: bool = False, vat: bool = True
    ) -> str | datetime:
        """Get tomorrow specific price and time."""
        if not self.tomorrow_available:
            return None

        dataset = self.prices_tomorrow
        res = None

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
