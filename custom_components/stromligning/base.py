"""Entity base definitions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription

from .api import StromligningAPI
from .const import UPDATE_SIGNAL


@dataclass(frozen=True)
class StromligningBaseEntityDescriptionMixin:
    """Describes a basic Stromligning entity."""

    value_fn: Callable[[StromligningAPI], bool | str | int | float | datetime | None]


@dataclass(frozen=True)
class StromligningSensorEntityDescription(
    SensorEntityDescription, StromligningBaseEntityDescriptionMixin
):
    """Describes a Stromligning sensor."""

    unit_fn: Callable[[StromligningAPI], None] | None = None
    update_signal: str = UPDATE_SIGNAL


@dataclass(frozen=True)
class StromligningBinarySensorEntityDescription(
    BinarySensorEntityDescription, StromligningBaseEntityDescriptionMixin
):
    """Describes a Stromligning sensor."""

    unit_fn: Callable[[StromligningAPI], None] | None = None


PriceValueGetter = Callable[[dict[str, Any]], str | float | int | None]


def _get_final_period_end(prices: list[dict[str, Any]], aggregation: str) -> datetime:
    """Return the correct end for the last price period in a dataset."""
    if len(prices) >= 2:
        return prices[-1]["date"] + (prices[-1]["date"] - prices[-2]["date"])

    interval = timedelta(minutes=15) if aggregation == "15m" else timedelta(hours=1)
    return prices[-1]["date"] + interval


def build_price_attributes(
    prices: list[dict[str, Any]],
    value_getter: PriceValueGetter,
    aggregation: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build price attributes with deterministic period boundaries."""
    if not prices:
        return {"prices": []}

    price_set: list[dict[str, Any]] = []

    for index, price in enumerate(prices):
        end = (
            prices[index + 1]["date"]
            if index < len(prices) - 1
            else _get_final_period_end(prices, aggregation)
        )
        price_set.append(
            {
                "price": value_getter(price),
                "start": price["date"],
                "end": end,
            }
        )

    return {"prices": price_set}
