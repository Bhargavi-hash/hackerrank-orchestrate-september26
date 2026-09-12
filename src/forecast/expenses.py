"""Debit gates and application of externally supplied, permitted modifications."""
from dataclasses import replace
from decimal import Decimal
from datetime import date
from src.models.event import FinancialEvent
from src.models.profile import FinancialProfile
from .simulation_models import (AppliedSpendingChange, CashFlowOccurrence,
                                SpendingChangeEffect)


def debit_is_includable(event: FinancialEvent, request_date: date) -> bool:
    if event.direction != 'debit':
        return False
    if event.status in {'pending', 'scheduled'}:
        return True
    return (event.status == 'settled' and event.settlement_date is not None
            and event.settlement_date > request_date)


def apply_spending_change(flow: CashFlowOccurrence, change: SpendingChangeEffect,
                          profile: FinancialProfile) -> tuple[CashFlowOccurrence, AppliedSpendingChange]:
    """Protected precedence, preference, flexibility and source floor still apply.

    Modification requires recurrence identity. It changes the obligation, never
    introduces a synthetic credit. Event IDs can target their inferred series.
    """
    if flow.direction != 'debit' or flow.series_id is None:
        raise ValueError(f'{change.target_id}: spending changes require recurring debit')
    if flow.category in profile.expense_categories_to_protect:
        raise ValueError(f'{change.target_id}: protected category')
    stop = change.operation == 'stop'
    allowed = (profile.expense_categories_user_is_willing_to_stop if stop else
               profile.expense_categories_user_is_willing_to_reduce)
    flexibility = 'stoppable' if stop else 'reducible'
    if flow.category not in allowed or flow.flexibility not in {flexibility, 'reducible_or_stoppable'}:
        raise ValueError(f'{change.target_id}: modification not permitted')
    amount = Decimal('0') if stop else change.new_amount
    if amount > flow.amount:
        raise ValueError('reduction cannot increase an occurrence')
    if not stop and flow.minimum_allowed_amount is not None and amount < flow.minimum_allowed_amount:
        raise ValueError('reduction below event minimum_allowed_amount')
    effect = AppliedSpendingChange(change.target_id, flow.source_id, change.operation,
                                   flow.amount, amount, flow.currency)
    return replace(flow, amount=amount), effect
