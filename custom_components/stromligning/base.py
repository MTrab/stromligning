"""Entity base definitions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_utils

from .api import StromligningAPI
from .coordinator import StromligningCoordinator


class StromligningEntity(CoordinatorEntity[StromligningCoordinator]):
    """Subscribe to entry-scoped updates and retain usable cached prices."""

    @property
    def available(self) -> bool:
        """Keep valid cached intervals usable even during a failed fetch."""
        return (
            self.coordinator.last_update_success
            or self.api.current_period() is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write values and attributes after either a fetch or local boundary."""
        self.handle_update()


@dataclass(frozen=True)
class StromligningBaseEntityDescriptionMixin:
    """Describes a basic Stromligning entity."""

    value_fn: Callable[[StromligningAPI], bool | str | int | float | datetime | None]


@dataclass(frozen=True)
class StromligningSensorEntityDescription(
    SensorEntityDescription, StromligningBaseEntityDescriptionMixin
):
    """Describes a Stromligning sensor."""


@dataclass(frozen=True)
class StromligningBinarySensorEntityDescription(
    BinarySensorEntityDescription, StromligningBaseEntityDescriptionMixin
):
    """Describes a Stromligning binary sensor."""


PriceValueGetter = Callable[[dict[str, Any]], str | float | int | None]


def build_price_attributes(
    prices: list[dict[str, Any]],
    value_getter: PriceValueGetter,
    aggregation: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build local price intervals using the configured duration."""
    interval = timedelta(minutes=15) if aggregation == "15m" else timedelta(hours=1)
    price_set: list[dict[str, Any]] = []

    for price in prices:
        end = dt_utils.as_local(dt_utils.as_utc(price["date"]) + interval)
        price_set.append(
            {
                "price": value_getter(price),
                "start": price["date"],
                "end": end,
            }
        )

    return {"prices": price_set}
