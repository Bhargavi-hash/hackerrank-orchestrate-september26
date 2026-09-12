"""Supplied offers only; no plan generation or eligibility yet."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from .base import SourceRecord


@dataclass(frozen=True)
class PaymentOption(SourceRecord):
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Decimal | None
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: Decimal | None
    total_payable_amount: Decimal | None
