from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from .base import SourceRecord


@dataclass(frozen=True)
class FinancialEvent(SourceRecord):
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Decimal | None
    currency: str
    event_date: date
    settlement_date: date | None
    status: str
    linked_event_id: str | None
    flexibility: str
    minimum_allowed_amount: Decimal | None


def is_cash_event(event: FinancialEvent) -> bool:
    """Direction gate only, NOT permission to count this event as available cash.

    Status, timing, and lifecycle treatment belong to later phases.
    """
    if event.direction == "non_cash":
        return False
    if event.direction not in {"debit", "credit"}:
        raise ValueError(f"Unknown direction: {event.direction!r}")
    return True
