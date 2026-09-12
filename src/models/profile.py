from dataclasses import dataclass
from decimal import Decimal
from .base import SourceRecord


@dataclass(frozen=True)
class FinancialProfile(SourceRecord):
    user_id: str
    home_currency: str
    current_available_balance: Decimal | None
    minimum_balance_to_keep: Decimal | None
    financial_priorities: tuple[str, ...]
    expense_categories_to_protect: frozenset[str]
    expense_categories_user_is_willing_to_reduce: frozenset[str]
    expense_categories_user_is_willing_to_stop: frozenset[str]
    payment_methods_user_will_consider: frozenset[str]
    max_installment_months: int | None
