"""Entity base definitions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.util import dt as dt_utils

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


@staticmethod
def get_next_midnight() -> datetime:
    """Return a datetime for the next midnight."""
    return dt_utils.as_local(
        datetime.fromisoformat(
            (dt_utils.now() + timedelta(days=1))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
    )
