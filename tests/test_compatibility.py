"""Check that the integration loads on the oldest supported Home Assistant."""

import ast
from pathlib import Path

import pytest

SOURCES = sorted(
    Path(__file__).parents[1].joinpath("custom_components/stromligning").glob("*.py")
)


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_source_parses_on_python_3_13(source: Path) -> None:
    """Home Assistant 2025.8, the minimum in hacs.json, runs Python 3.13."""
    ast.parse(source.read_text(encoding="utf-8"), str(source), feature_version=(3, 13))
