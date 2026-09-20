from decimal import Decimal

from backend.storage.dynamodb import from_dynamodb, to_dynamodb


def test_to_dynamodb_converts_nested_floats():
    value = {
        "confidence": 0.84,
        "nested": [1.25, {"score": 0.5}],
    }

    converted = to_dynamodb(value)

    assert converted["confidence"] == Decimal("0.84")
    assert converted["nested"][0] == Decimal("1.25")
    assert converted["nested"][1]["score"] == Decimal("0.5")


def test_from_dynamodb_restores_numbers():
    value = {
        "whole": Decimal("2"),
        "fractional": Decimal("0.75"),
        "nested": [Decimal("1.5")],
    }

    restored = from_dynamodb(value)

    assert restored == {
        "whole": 2,
        "fractional": 0.75,
        "nested": [1.5],
    }
