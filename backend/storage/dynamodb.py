from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def to_dynamodb(value: Any) -> Any:
    """Convert Python/JSON values into DynamoDB-safe values.

    boto3's DynamoDB resource layer rejects Python float values. Floats are
    represented as Decimal from their string form to preserve human-facing
    decimal values without binary floating-point artifacts.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Mapping):
        return {str(key): to_dynamodb(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamodb(item) for item in value]
    if isinstance(value, set):
        return {to_dynamodb(item) for item in value}
    return value


def from_dynamodb(value: Any) -> Any:
    """Convert DynamoDB Decimal values back to normal Python JSON values."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, Mapping):
        return {key: from_dynamodb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_dynamodb(item) for item in value]
    if isinstance(value, tuple):
        return tuple(from_dynamodb(item) for item in value)
    if isinstance(value, set):
        return {from_dynamodb(item) for item in value}
    return value
