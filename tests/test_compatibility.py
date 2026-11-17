"""Check that the integration loads on the oldest supported Home Assistant."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from custom_components.stromligning.naming import device_name

SOURCES = sorted(
    Path(__file__).parents[1].joinpath("custom_components/stromligning").glob("*.py")
)


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_source_parses_on_python_3_13(source: Path) -> None:
    """Home Assistant 2025.8, the minimum in hacs.json, runs Python 3.13."""
    ast.parse(source.read_text(encoding="utf-8"), str(source), feature_version=(3, 13))


ENTRY = SimpleNamespace(entry_id="entry", data={"name": "Configured name"})


def test_device_lookup_on_current_home_assistant():
    """The lookup that replaces the deprecated one is used where it exists."""
    registry = Mock()
    registry.async_get_device_by_identifier.return_value = SimpleNamespace(name="New")
    with patch("homeassistant.helpers.device_registry.async_get") as async_get:
        async_get.return_value = registry
        assert device_name(None, ENTRY) == "New"
    registry.async_get_device_by_identifier.assert_called_once_with(
        ("stromligning", "entry"), "entry"
    )
    registry.async_get_device.assert_not_called()


def test_device_lookup_on_older_home_assistant():
    """Home Assistant 2026.2 and older only have the earlier lookup."""
    registry = Mock(spec=["async_get_device"])
    registry.async_get_device.return_value = SimpleNamespace(name="Old")
    with patch("homeassistant.helpers.device_registry.async_get") as async_get:
        async_get.return_value = registry
        assert device_name(None, ENTRY) == "Old"
    registry.async_get_device.assert_called_once_with(
        identifiers={("stromligning", "entry")}
    )


def test_device_name_without_a_registered_device():
    """Before the device exists, the name comes from the entry."""
    registry = Mock()
    registry.async_get_device_by_identifier.return_value = None
    with patch("homeassistant.helpers.device_registry.async_get") as async_get:
        async_get.return_value = registry
        assert device_name(None, ENTRY) == "Configured name"
