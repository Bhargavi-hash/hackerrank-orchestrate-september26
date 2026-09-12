"""Narrow structured credit gate, separate from historical recurrence inference."""
from datetime import date
import re
from typing import Iterable
from src.models.event import FinancialEvent
from .recurrence_models import RecurringSeries
from .recurrence import normalize_description


def is_confirmed_scheduled_income(event: FinancialEvent) -> bool:
    """Only the dataset's explicit 'Next confirmed salary' assertion qualifies.

    All 47 scheduled credits use this assertion. Scheduled bonuses, refunds,
    gains and generic scheduled salary are not promoted to confirmed cash.
    Future evidence layers can instead supply an explicit amended occurrence.
    """
    return (event.direction == 'credit' and event.status == 'scheduled'
            and event.event_type == 'income' and event.category == 'salary'
            and normalize_description(event.description) == 'next confirmed salary')


def credit_is_includable(event: FinancialEvent, request_date: date) -> bool:
    if event.direction != 'credit':
        return False
    if event.status == 'scheduled':
        return (is_confirmed_scheduled_income(event)
                and (event.settlement_date or event.event_date) >= request_date)
    return (event.status == 'settled' and event.settlement_date is not None
            and event.settlement_date > request_date)


def terminating_payroll_marker(series: RecurringSeries, events: Iterable[FinancialEvent],
                               start: date) -> FinancialEvent | None:
    """A later settled final-payroll assertion invalidates continuation of older
    regular salary history. This is a source amendment gate, not a new recurrence
    estimator. A subsequent regular historical payment can establish resumption.
    """
    if series.direction != 'credit' or series.category != 'salary':
        return None
    markers = [e for e in events if e.user_id == series.user_id and e.currency == series.currency
               and e.direction == 'credit' and e.event_type == 'income' and e.category == 'salary'
               and e.status == 'settled' and e.settlement_date is not None
               and max(series.dates) < e.event_date < start and e.settlement_date < start
               and re.search(r'\bfinal\b', normalize_description(e.description))]
    return max(markers, key=lambda e: (e.event_date,e.event_id)) if markers else None
