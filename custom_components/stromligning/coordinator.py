"""Shared API refresh and independent local price-boundary updates."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_utils
from pystromligning.exceptions import (
    FixedPriceRequired,
    InvalidAPIResponse,
    TooManyRequests,
)
from requests.exceptions import RequestException

from .api import StromligningAPI
from .const import CONF_FORECASTS, DOMAIN

LOGGER = logging.getLogger(__name__)

type StromligningConfigEntry = ConfigEntry[StromligningCoordinator]


class StromligningCoordinator(DataUpdateCoordinator[StromligningAPI]):
    """Own the client, fetch status, and all scheduling for one entry."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: StromligningAPI
    ) -> None:
        """Initialize without periodic coordinator polling."""
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry)
        self.api = api
        self.entry = entry
        self._lock = asyncio.Lock()
        self._api_unsub = None
        self._local_unsub = None
        self._closed = False
        self._located = False
        self._retry_at = None
        self.rate_limit_until = None

    async def _async_update_data(self) -> StromligningAPI:
        """Serialize synchronous client access and publish only valid snapshots."""
        async with self._lock:
            if self._closed:
                return self.api
            if (
                self.rate_limit_until is not None
                and dt_utils.utcnow() < self.rate_limit_until
            ):
                raise UpdateFailed("API rate limit; waiting for the retry deadline")
            try:
                if not self._located:
                    await self.api.set_location()
                    self._located = True
                await self.api.update_prices()
            except FixedPriceRequired as err:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"fixed_price_required_{self.entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="fixed_price_required",
                    translation_placeholders={"name": self.entry.title},
                )
                raise ConfigEntryError(
                    translation_domain=DOMAIN,
                    translation_key="fixed_price_required",
                ) from err
            except TooManyRequests as err:
                self._retry_at = dt_utils.utcnow() + timedelta(minutes=15)
                self.rate_limit_until = self._retry_at
                raise UpdateFailed("API rate limit; retry in 15 minutes") from err
            except (
                InvalidAPIResponse,
                RequestException,
                TimeoutError,
                KeyError,
                IndexError,
                ValueError,
                TypeError,
            ) as err:
                self._retry_at = dt_utils.utcnow() + self.api.period_length
                raise UpdateFailed(
                    "Unable to retrieve valid electricity prices"
                ) from err
            ir.async_delete_issue(
                self.hass, DOMAIN, f"fixed_price_required_{self.entry.entry_id}"
            )
            self._retry_at = None
            self.rate_limit_until = None
            return self.api

    @callback
    def start(self) -> None:
        """Register one local boundary subscription and one API deadline."""
        self._local_unsub = async_track_time_change(
            self.hass,
            self._local_update,
            minute="/15" if self.api.get_aggregation() == "15m" else 0,
            second=1,
        )
        self._schedule()
        self.async_update_listeners()

    @callback
    def close(self) -> None:
        """Cancel callbacks, including callbacks after an in-flight request."""
        self._closed = True
        for unsubscribe in (self._api_unsub, self._local_unsub):
            if unsubscribe is not None:
                unsubscribe()
        self._api_unsub = self._local_unsub = None

    def _next_deadline(self):
        """Calculate the next daily, forecast, missing-data, or retry deadline."""
        now = dt_utils.now()
        utc_now = dt_utils.as_utc(now)
        hour, minute, second = map(int, self.api.next_update.split(":"))
        daily = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if daily <= now:
            daily += timedelta(days=1)
        deadlines = [dt_utils.as_utc(daily)]
        if self.entry.options.get(CONF_FORECASTS, False):
            forecast = utc_now.replace(
                hour=utc_now.hour // 6 * 6, minute=10, second=0, microsecond=0
            )
            if forecast <= utc_now:
                forecast += timedelta(hours=6)
            deadlines.append(forecast)
        if not self.api.tomorrow_available:
            boundary = utc_now.replace(second=1, microsecond=0)
            step = self.api.period_length
            boundary = boundary.replace(
                minute=(boundary.minute // (step.seconds // 60)) * (step.seconds // 60)
            )
            if boundary <= utc_now:
                boundary += step
            if dt_utils.as_local(boundary).hour >= 14:
                deadlines.append(boundary)
            if not self.api.prices_tomorrow:
                deadlines.append(
                    dt_utils.as_utc(
                        (now + timedelta(days=1)).replace(
                            hour=0, minute=0, second=1, microsecond=0
                        )
                    )
                )
        if self._retry_at is not None:
            return self._retry_at
        return min(deadlines)

    @callback
    def _schedule(self) -> None:
        """Keep the displayed deadline identical to the actual timer."""
        if self._closed:
            return
        if self._api_unsub is not None:
            self._api_unsub()
        self.api.scheduled_update = self._next_deadline()
        self._api_unsub = async_track_point_in_utc_time(
            self.hass, self._fetch, self.api.scheduled_update
        )

    async def _fetch(self, now) -> None:
        """Refresh at the scheduled deadline and schedule the next attempt."""
        if self._closed:
            return
        self._api_unsub = None
        await self.async_refresh()
        self._schedule()
        if not self._closed:
            self.async_update_listeners()

    async def _local_update(self, now) -> None:
        """Update local periods and rollover without requesting data."""
        async with self._lock:
            if self._closed:
                return
            await self.api.prepare_data()
            self.async_update_listeners()
