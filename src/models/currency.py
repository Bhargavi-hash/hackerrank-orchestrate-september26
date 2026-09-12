from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from .base import SourceRecord


@dataclass(frozen=True)
class ExchangeRate(SourceRecord):
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal | None
