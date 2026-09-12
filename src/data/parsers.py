"""Strict, shared CSV scalar and pipe-list parsing."""
import re
from datetime import date, datetime
from decimal import Decimal


def parse_money(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
        raise ValueError("expected a finite decimal string")
    return Decimal(value)


def parse_collection(value: str) -> tuple[str, ...]:
    """Pipe-delimited dataset format; preserve order, deduplicate tokens."""
    if not value.strip():
        return ()
    tokens = tuple(part.strip() for part in value.split("|"))
    if any(not token for token in tokens):
        raise ValueError("empty token in pipe-delimited collection")
    return tuple(dict.fromkeys(tokens))


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError("expected true or false")
    return normalized == "true"


def parse_date(value: str) -> date | None:
    if not value.strip():
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def parse_int(value: str) -> int | None:
    if not value.strip():
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("expected nonnegative integer")
    return int(value)


def parse_id(value: str) -> str | None:
    if not value.strip():
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError("ID must contain only letters, digits, underscores or hyphens")
    return value
