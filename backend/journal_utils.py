"""
Shared Decimal <-> bson.Decimal128 conversion for the journal collections.

Motor/pymongo don't auto-convert Python Decimal to Decimal128 on write (or
back on read) — this has to happen explicitly at the Mongo I/O boundary.
Used by both journal_routes.py (writes) and journal_analytics.py (reads).
"""
from decimal import Decimal

from bson import Decimal128


def to_mongo(value):
    """Recursively convert Decimal -> Decimal128 for a dict/list about to be written to Mongo."""
    if isinstance(value, Decimal):
        return Decimal128(str(value))
    if isinstance(value, dict):
        return {k: to_mongo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_mongo(v) for v in value]
    return value


def from_mongo(value):
    """Recursively convert Decimal128 -> Decimal for a doc read back from Mongo."""
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, dict):
        return {k: from_mongo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_mongo(v) for v in value]
    return value
