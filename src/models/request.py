from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from .base import SourceRecord


@dataclass(frozen=True)
class Request(SourceRecord):
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal | None
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class SampleRequest(Request):
    """Supplied labels only; no decision computation."""
    amount_safe_to_pay: Decimal | None
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str
    decision_explanation: str


@dataclass(frozen=True)
class OutputTemplateRow(SourceRecord):
    request_id: str
    amount_safe_to_pay: Decimal | None
    affordability_status: str | None
    recommended_payment_method: str | None
    payment_plan: str | None
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str | None
    decision_explanation: str | None
