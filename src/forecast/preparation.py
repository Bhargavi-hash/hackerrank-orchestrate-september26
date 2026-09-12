"""Prepare recurrence and explicit rows; never apply balances or read messages."""
from dataclasses import replace
from datetime import date
from typing import Iterable
from src.data.indexes import DataIndexes
from src.evidence.resolver import resolve_linked_component
from src.models.event import FinancialEvent, is_cash_event
from .expenses import debit_is_includable
from .income import credit_is_includable, terminating_payroll_marker
from .recurrence import infer_recurring_series, normalize_description, project_recurring_series
from .recurrence_models import DEFAULT_POLICY, RecurrencePolicy, RecurringSeries
from .simulation_models import (CashFlowOccurrence, DEFAULT_TIMING_POLICY,
    FutureEventDateSource, PreparedForecast, TimingPolicy)
from .timeline import horizon_dates, occurrence_order


def effective_event_date(event: FinancialEvent, start: date, policy: TimingPolicy) -> date:
    """Overdue/unsettled debits reserve today; absent settlement uses event date.

    Pending reserves may move to their future settlement date under the default.
    That timing remains provisional. Historical settled rows are gated separately.
    """
    selected = (event.event_date if policy.future_event_date_source == FutureEventDateSource.EVENT_DATE
                else event.settlement_date or event.event_date)
    return max(start, selected)


def superseding_lifecycle_event(event: FinancialEvent, indexes: DataIndexes,
                               start: date) -> FinancialEvent | None:
    """Only obvious same-cash pending duplication: matching settled row or a
    later cancellation directly referencing this attempt. Never cancel an entire
    component merely because one failed/cancelled attempt exists in it.
    Ambiguous components are retained with diagnostics by prepare_forecast.
    """
    if event.status != 'pending':
        return None
    peers = resolve_linked_component(event.event_id, indexes)
    for peer in peers:
        same_cash = (peer.event_id != event.event_id and peer.direction == event.direction
                     and peer.currency == event.currency and peer.category == event.category
                     and peer.amount == event.amount and event.amount is not None)
        settled = (peer.status == 'settled' and peer.settlement_date is not None
                   and event.event_date <= peer.settlement_date <= horizon_dates(start)[-1])
        cancelled = (peer.status == 'cancelled' and peer.linked_event_id == event.event_id
                     and event.event_date <= peer.event_date <= start)
        if same_cash and (settled or cancelled):
            return peer
    return None


def matching_series(event: FinancialEvent, series: Iterable[RecurringSeries],
                    indexes: DataIndexes) -> RecurringSeries | None:
    """Unique matching regular salary, or exact description among historical
    members with the same category/type/direction/currency. Category alone never
    equates two purchases. Dates are matched separately during reconciliation.
    """
    matches = []
    for item in series:
        if not item.is_recurring or (item.user_id, item.direction, item.currency,
                item.category, item.event_type) != (event.user_id, event.direction,
                event.currency, event.category, event.event_type):
            continue
        descriptions = {normalize_description(indexes.events_by_event_id[key].description)
                        for key in item.event_ids}
        if (normalize_description(event.description) in descriptions or
            (event.direction == 'credit' and event.category == 'salary'
             and credit_is_includable(event, item.as_of))):
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def reconcile_projected_and_explicit_occurrences(
    projected: Iterable[CashFlowOccurrence], explicit: Iterable[CashFlowOccurrence],
) -> tuple[CashFlowOccurrence, ...]:
    """Explicit beats synthetic only for a unique series AND exact occurrence
    date, currency, direction and user match. No fuzzy date tolerance. Preserve
    independent explicit charges; reject multiple concrete matches as ambiguous.
    """
    projected, explicit = tuple(projected), tuple(explicit)
    def key(flow):
        return flow.user_id, flow.series_id, flow.date, flow.direction, flow.currency
    concrete = {}
    for flow in explicit:
        if flow.series_id:
            concrete.setdefault(key(flow), []).append(flow)
    result = []
    for flow in projected:
        matches = concrete.get(key(flow), ()) if flow.series_id else ()
        if len(matches) > 1:
            raise ValueError(f'ambiguous explicit recurrence match: {flow.series_id} {flow.date}')
        if not matches:
            result.append(flow)
    return tuple(sorted((*result, *explicit), key=occurrence_order))


def prepare_forecast(indexes: DataIndexes, user_id: str, start: date,
                     timing_policy: TimingPolicy = DEFAULT_TIMING_POLICY,
                     recurrence_policy: RecurrencePolicy = DEFAULT_POLICY) -> PreparedForecast:
    """Historical source predictions and known future records stay separate.

    Recurring regular salary remains a history-based assumption, NOT confirmation.
    Missing future amounts are surfaced as incomplete, never converted to zero.
    No message/image interpretation or balance replay occurs here.
    """
    if user_id not in indexes.profile_by_user_id:
        raise ValueError(f'unknown user {user_id}')
    end = horizon_dates(start)[-1]
    events = indexes.events_by_user_id.get(user_id, ())
    inferred = infer_recurring_series(events, start, recurrence_policy)
    projected, explicit, unresolved, diagnostics = [], [], [], []
    for series in inferred.series:
        marker = terminating_payroll_marker(series, events, start)
        if marker is not None:
            diagnostics.append(f'{series.series_id}: continuation suppressed by {marker.event_id} final payroll')
            continue
        members = [indexes.events_by_event_id[key] for key in series.event_ids]
        latest = max(members, key=lambda e: (e.event_date, e.event_id))
        flexibility = latest.flexibility if len({e.flexibility for e in members}) == 1 else 'fixed'
        floors = [e.minimum_allowed_amount for e in members if e.minimum_allowed_amount is not None]
        for flow in project_recurring_series(series, start, end):
            projected.append(CashFlowOccurrence(series.series_id, user_id, flow.date, flow.amount,
                flow.currency, flow.direction, flow.category, 'recurrence_projection', 'projected',
                series.event_type, flow.confidence.value, series.series_id, flow.source_event_ids,
                latest.description, flexibility, max(floors) if floors else None))
        if series.is_recurring and series.direction == 'credit':
            diagnostics.append(f'{series.series_id}: historical salary forecast is not future confirmation')
    ignored_pending_credits = 0
    components_seen = set()
    for event in sorted(events, key=lambda e: e.event_id):
        if not is_cash_event(event):
            continue
        if event.status == 'pending' and event.direction == 'credit':
            ignored_pending_credits += 1
            diagnostics.append(f'{event.event_id}: ignored pending credit')
        if not (debit_is_includable(event, start) or credit_is_includable(event, start)):
            continue
        day = effective_event_date(event, start, timing_policy)
        if day > end:
            continue
        superseding = superseding_lifecycle_event(event, indexes, start)
        if superseding:
            diagnostics.append(f'{event.event_id}: superseded by linked {superseding.event_id}')
            continue
        component = resolve_linked_component(event.event_id, indexes)
        component_ids = tuple(e.event_id for e in component)
        active = [e for e in component if e.status in {'pending', 'scheduled'}
                  and e.direction == event.direction
                  and superseding_lifecycle_event(e, indexes, start) is None]
        if len(active) > 1 and component_ids not in components_seen:
            diagnostics.append(f'{component_ids}: multiple active lifecycle rows; unresolved duplication')
            unresolved.append(f'lifecycle:{component_ids}')
            components_seen.add(component_ids)
        if event.amount is None:
            unresolved.append(f'{event.event_id}: missing future {event.direction} amount')
            continue
        series = matching_series(event, inferred.series, indexes)
        provenance = 'pending_debit' if event.status == 'pending' else f'{event.status}_event'
        explicit.append(CashFlowOccurrence(event.event_id, user_id, day, event.amount,
            event.currency, event.direction, event.category, provenance, event.status,
            event.event_type, 'explicit', series.series_id if series else None,
            tuple(sorted({event.event_id, *(series.event_ids if series else ())})), event.description, event.flexibility, event.minimum_allowed_amount,
            event.settlement_date or event.event_date))
    return PreparedForecast(tuple(sorted(projected, key=occurrence_order)),
        tuple(sorted(explicit, key=occurrence_order)), tuple(sorted(unresolved)),
        tuple(sorted(diagnostics)), ignored_pending_credits)
