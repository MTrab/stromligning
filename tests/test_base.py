"""Tests for shared period-building helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.stromligning.base import build_price_attributes


def test_build_price_attributes_returns_empty_list_for_empty_input() -> None:
    """An empty dataset should not leave behind a dangling partial period."""
    assert build_price_attributes([], lambda price: price["price"]["total"], "1h") == {
        "prices": []
    }


def test_build_price_attributes_uses_next_start_and_final_interval() -> None:
    """The final period end should be derived from the dataset interval."""
    prices = [
        {
            "date": datetime(2026, 2, 24, 21, 0, tzinfo=UTC),
            "price": {"total": 1.1},
        },
        {
            "date": datetime(2026, 2, 24, 22, 0, tzinfo=UTC),
            "price": {"total": 1.2},
        },
        {
            "date": datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
            "price": {"total": 1.3},
        },
    ]

    result = build_price_attributes(
        prices,
        lambda price: price["price"]["total"],
        "1h",
    )

    assert result == {
        "prices": [
            {
                "price": 1.1,
                "start": datetime(2026, 2, 24, 21, 0, tzinfo=UTC),
                "end": datetime(2026, 2, 24, 22, 0, tzinfo=UTC),
            },
            {
                "price": 1.2,
                "start": datetime(2026, 2, 24, 22, 0, tzinfo=UTC),
                "end": datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
            },
            {
                "price": 1.3,
                "start": datetime(2026, 2, 24, 23, 0, tzinfo=UTC),
                "end": datetime(2026, 2, 25, 0, 0, tzinfo=UTC),
            },
        ]
    }


def test_build_price_attributes_uses_aggregation_fallback_for_single_value() -> None:
    """A single 15 minute datapoint should still yield the right period end."""
    prices = [
        {
            "date": datetime(2026, 2, 24, 23, 45, tzinfo=UTC),
            "price": {"total": 1.3},
        }
    ]

    result = build_price_attributes(
        prices,
        lambda price: price["price"]["total"],
        "15m",
    )

    assert result == {
        "prices": [
            {
                "price": 1.3,
                "start": datetime(2026, 2, 24, 23, 45, tzinfo=UTC),
                "end": datetime(2026, 2, 25, 0, 0, tzinfo=UTC),
            }
        ]
    }
