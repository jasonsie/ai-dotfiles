"""The small readers a CLI's transcript lines share: each takes what a line may hold and gives a plain value."""
from __future__ import annotations

from datetime import datetime, timezone
import json


def when(value):
    """The aware datetime in an ISO 8601 string (the stores write UTC), or None."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def obj(value):
    return value if isinstance(value, dict) else {}


def items(value):
    """The dicts in a list."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def text(value):
    return value if isinstance(value, str) else ''


def args(value):
    """A tool call's arguments as a dict: given as one, or as a JSON string; else empty."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return obj(value)
