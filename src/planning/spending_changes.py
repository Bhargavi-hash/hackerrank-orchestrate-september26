"""Preference/flexibility primitives; recurrence eligibility is deferred."""
from src.models.event import FinancialEvent
from src.models.profile import FinancialProfile


def can_stop(event: FinancialEvent, profile: FinancialProfile) -> bool:
    return (
        event.user_id == profile.user_id
        and event.category not in profile.expense_categories_to_protect
        and event.category in profile.expense_categories_user_is_willing_to_stop
        and event.flexibility in {"stoppable", "reducible_or_stoppable"}
    )


def can_reduce(event: FinancialEvent, profile: FinancialProfile) -> bool:
    return (
        event.user_id == profile.user_id
        and event.category not in profile.expense_categories_to_protect
        and event.category in profile.expense_categories_user_is_willing_to_reduce
        and event.flexibility in {"reducible", "reducible_or_stoppable"}
    )
