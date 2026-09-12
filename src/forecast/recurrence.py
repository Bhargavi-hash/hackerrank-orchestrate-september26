"""Deterministic history inference; never balances, amendments or cash confirmation.

Historical eligibility uses both event and settlement dates strictly before as_of.
The configurable observation date is a recurrence experiment, not a future ledger
ordering decision. Missing amounts are excluded with diagnostics, never filled.
"""
import calendar
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, timedelta
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable

from src.data.indexes import build_linked_adjacency
from src.models.event import FinancialEvent, is_cash_event
from .recurrence_models import (
    DEFAULT_POLICY, Cadence, ConfidenceThresholds, HistoryDiagnostic,
    ProjectedOccurrence, RecurrenceConfidence, RecurrenceDiagnostics,
    RecurrencePolicy, RecurrenceResult, RecurringSeries,
)

D = Decimal
ARITHMETIC = Context(prec=40, rounding=ROUND_HALF_UP)
HIGH_FREQUENCY_CATEGORIES = frozenset({'groceries', 'dining', 'transport'})


def normalize_description(description: str) -> str:
    """Normalize Unicode/case/punctuation/spacing; retain all numbers and merchants."""
    text = unicodedata.normalize('NFKC', description).casefold()
    return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())


def description_family(event: FinancialEvent) -> str:
    """Only everyday variable-spend categories pool merchants; other text stays intact.

    Transport airfare stays separate: the dataset includes an airline ticket.
    Groceries/dining represent category budgets, not a claim of merchant identity.
    """
    normalized = normalize_description(event.description)
    if event.category in HIGH_FREQUENCY_CATEGORIES and event.direction == 'debit':
        if re.search(r'\b(airline|flight|airfare)\b', normalized):
            return normalized
        return f'variable_spend:{event.category}'
    return normalized


def recurrence_exclusion_reason(event: FinancialEvent, as_of: date) -> str | None:
    if not is_cash_event(event):
        return 'non_cash'
    if event.status != 'settled':
        return f'status:{event.status}'
    if event.settlement_date is None:
        return 'missing_settlement_date'
    if max(event.event_date, event.settlement_date) >= as_of:
        return 'not_historical'
    if event.amount is None:
        return 'missing_amount'
    if not isinstance(event.amount, Decimal) or not event.amount.is_finite() or event.amount < 0:
        raise ValueError(f'{event.event_id}: expected nonnegative finite Decimal amount')
    if event.direction == 'credit':
        text = normalize_description(event.description)
        if event.event_type != 'income' or event.category != 'salary':
            return 'not_salary_income'
        if not re.search(r'\b(salary|payroll|wages)\b', text):
            return 'unconfirmed_income_family'
        if re.search(r'\b(bonus|commission|prorated|first|final|previous|temporary|seasonal|arrears)\b|before leave', text):
            return 'non_regular_salary'
    elif event.event_type not in {'expense', 'subscription', 'debt_payment'}:
        return 'unsupported_debit_type'
    return None


def is_recurrence_evidence(event: FinancialEvent, as_of: date) -> bool:
    """Only settled, known historical cash expenses or identifiable regular salary."""
    return recurrence_exclusion_reason(event, as_of) is None


def prepare_history(events: Iterable[FinancialEvent], as_of: date) -> tuple[tuple[FinancialEvent, ...], tuple[HistoryDiagnostic, ...]]:
    """Use an as-of induced linked graph; future edges cannot change past history.

    Multiple settled cash rows in one component are ambiguous, so exclude the
    component from recurrence evidence. One settled row plus failed/authorization
    attempts is kept once. This does not resolve the component's financial value.
    """
    all_events = tuple(events)
    by_id = {e.event_id: e for e in all_events}
    if len(by_id) != len(all_events):
        raise ValueError('duplicate event ID in recurrence input')
    build_linked_adjacency(by_id)  # Phase 1 validates IDs and cross-user edges.
    visible = {e.event_id: e for e in all_events if e.event_date < as_of
               and (e.settlement_date is None or e.settlement_date < as_of)}
    induced = {key: replace(e, linked_event_id=e.linked_event_id if e.linked_event_id in visible else None)
               for key, e in visible.items()}
    adjacency = build_linked_adjacency(induced)
    visited: set[str] = set()
    ambiguous: set[str] = set()
    diagnostics = []
    for key in sorted(induced):
        if key in visited:
            continue
        pending, component = [key], set()
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current])
        visited.update(component)
        settled_cash = [visible[k] for k in component if visible[k].status == 'settled'
                        and is_cash_event(visible[k])]
        if len(settled_cash) > 1:
            ambiguous.update(component)
            diagnostics.append(HistoryDiagnostic(tuple(sorted(component)), 'ambiguous_linked_settlements_excluded'))
    kept = []
    for e in sorted(all_events, key=lambda e: e.event_id):
        reason = recurrence_exclusion_reason(e, as_of)
        if reason:
            diagnostics.append(HistoryDiagnostic((e.event_id,), reason))
        elif e.event_id not in ambiguous:
            kept.append(e)
    return tuple(kept), tuple(diagnostics)


def recurrence_identity(event: FinancialEvent, method: str) -> tuple[str, ...]:
    # Currency always partitions series; amounts in different units never mix.
    common = (event.user_id, event.direction, event.currency)
    if method == 'exact':
        return (*common, event.event_type, normalize_description(event.description))
    if method == 'category':
        return (*common, event.event_type, event.category)
    if method == 'family':
        return (*common, event.category, description_family(event))
    raise ValueError(f'unknown identity method {method}')


def observation_date(event: FinancialEvent, policy: RecurrencePolicy) -> date:
    result = getattr(event, policy.date_source)
    if result is None:
        raise ValueError(f'{event.event_id}: missing {policy.date_source}')
    return result


def decimal_median(values: Iterable[Decimal]) -> Decimal:
    values = sorted(values)
    if not values:
        raise ValueError('median requires observations')
    with localcontext(ARITHMETIC):
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / D(2)


def calendar_anchor(dates: tuple[date, ...]) -> tuple[int, bool] | None:
    if len(dates) < 3:
        return None
    months = [d.year * 12 + d.month for d in dates]
    if any(b - a != 1 for a, b in zip(months, months[1:])):
        return None
    if all(d.day == calendar.monthrange(d.year, d.month)[1] for d in dates):
        return 31, True
    anchor = max(d.day for d in dates)
    if all(d.day == min(anchor, calendar.monthrange(d.year, d.month)[1]) for d in dates):
        return anchor, False
    return None


def estimate_cadence(dates: tuple[date, ...], method: str) -> Cadence | None:
    if method not in {'calendar_aware', 'median', 'recent_median', 'mode'}:
        raise ValueError(f'unknown cadence method {method}')
    intervals = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not intervals or any(i <= 0 for i in intervals):
        return None
    anchor = calendar_anchor(dates)
    if method == 'calendar_aware' and anchor:
        return Cadence('calendar_month', None, *anchor)
    if method == 'mode':
        counts = Counter(intervals)
        # Deterministic tie: the smallest modal interval.
        interval = min(counts, key=lambda x: (-counts[x], x))
    else:
        selected = intervals[-3:] if method == 'recent_median' else intervals
        interval = int(decimal_median(map(D, selected)).to_integral_value(rounding=ROUND_HALF_UP))
    return Cadence('fixed_days', max(1, interval))


def estimate_amount(amounts: tuple[Decimal, ...], method: str) -> Decimal:
    """40-digit Decimal arithmetic; quantize once to 0.01, ROUND_HALF_UP.

    This is a projection precision convention, not final currency/payment rounding.
    """
    if not amounts or any(not isinstance(a, Decimal) or not a.is_finite() or a < 0 for a in amounts):
        raise ValueError('amount observations must be nonnegative finite Decimals')
    with localcontext(ARITHMETIC):
        if method == 'latest':
            result = amounts[-1]
        elif method in {'mean_last_3', 'mean_last_5'}:
            recent = amounts[-int(method[-1]):]
            result = sum(recent, D(0)) / D(len(recent))
        elif method in {'median_last_3', 'median_last_5'}:
            result = decimal_median(amounts[-int(method[-1]):])
        elif method == 'max_last_3':
            result = max(amounts[-3:])
        else:
            raise ValueError(f'unknown amount method {method}')
        return result.quantize(D('0.01'))


def score_recurrence_confidence(diagnostics: RecurrenceDiagnostics, thresholds: ConfidenceThresholds) -> RecurrenceConfidence:
    """A mechanical evidence grade, never a probability or salary confirmation."""
    n = diagnostics.observation_count
    if n < 2:
        return RecurrenceConfidence.INSUFFICIENT
    if (n < thresholds.minimum_observations or diagnostics.maximum_interval_deviation is None
            or diagnostics.maximum_interval_deviation > thresholds.maximum_interval_deviation
            or diagnostics.stale_cycles is None or diagnostics.stale_cycles > thresholds.maximum_stale_cycles
            or any(r in diagnostics.reasons for r in ('mixed_categories', 'mixed_income_identity', 'same_day_observations'))):
        return RecurrenceConfidence.LOW
    if (n >= thresholds.high_observations
            and diagnostics.maximum_interval_deviation <= thresholds.high_interval_deviation
            and diagnostics.amount_cv is not None and diagnostics.amount_cv <= thresholds.high_amount_cv):
        return RecurrenceConfidence.HIGH
    return RecurrenceConfidence.MEDIUM


def infer_series(events: tuple[FinancialEvent, ...], as_of: date, policy: RecurrencePolicy) -> RecurringSeries:
    if not events:
        raise ValueError('cannot infer an empty series')
    key = recurrence_identity(events[0], policy.identity_method)
    if any(recurrence_identity(e, policy.identity_method) != key or not is_recurrence_evidence(e, as_of) for e in events):
        raise ValueError('series must contain eligible history with one identity')
    events = tuple(sorted(events, key=lambda e: (observation_date(e, policy), e.event_id)))
    dates = tuple(observation_date(e, policy) for e in events)
    amounts = tuple(e.amount for e in events)
    cadence = estimate_cadence(dates, policy.cadence_method)
    descriptions = {normalize_description(e.description) for e in events}
    reasons = []
    if len({e.category for e in events}) > 1:
        reasons.append('mixed_categories')
    if events[0].direction == 'credit' and len(descriptions) > 1:
        reasons.append('mixed_income_identity')
    if len(set(dates)) != len(dates):
        reasons.append('same_day_observations')
    intervals = tuple(D((b-a).days) for a, b in zip(dates, dates[1:]))
    with localcontext(ARITHMETIC):
        median = decimal_median(intervals) if intervals else None
        mad = decimal_median(abs(i-median) for i in intervals) if intervals else None
        deviation = max(abs(i-median) for i in intervals) / median if median else None
        if cadence and cadence.model == 'calendar_month':
            deviation = D(0)  # Calendar residual is zero; raw interval MAD still retained.
        mean = sum(amounts, D(0)) / D(len(amounts))
        cv = (sum((a-mean)**2 for a in amounts) / D(len(amounts))).sqrt() / mean if mean else D(0)
        stale = D((as_of-dates[-1]).days) / median if median else None
        amount = estimate_amount(amounts, policy.amount_method)
        amount_model = policy.amount_method
        if (policy.spend_rate_method == 'rolling_28' and events[0].category in HIGH_FREQUENCY_CATEGORIES
                and cadence and cadence.days and cadence.days <= 14):
            if (dates[-1]-dates[0]).days >= 28:
                recent_spend = sum((a for a, day in zip(amounts, dates) if day > dates[-1]-timedelta(days=28)), D(0))
                amount = (recent_spend / D(28) * D(cadence.days)).quantize(D('0.01'))
                amount_model = 'rolling_28_scaled_to_cadence'
            else:
                reasons.append('rolling_28_insufficient_span_fallback')
    diagnostics = RecurrenceDiagnostics(len(events), median, mad, deviation, cv, len(descriptions), stale, tuple(reasons))
    confidence = score_recurrence_confidence(diagnostics, policy.thresholds)
    identity_text = json.dumps(key, ensure_ascii=True)
    series_id = 'series_' + hashlib.sha256(identity_text.encode()).hexdigest()[:20]
    return RecurringSeries(events[0].user_id, series_id, key, tuple(e.event_id for e in events),
                           events[0].event_type, events[0].category, description_family(events[0]),
                           events[0].direction, events[0].currency, dates, amounts, cadence, amount,
                           amount_model, confidence, diagnostics, as_of, policy)


def infer_recurring_series(events: Iterable[FinancialEvent], as_of: date,
                           policy: RecurrencePolicy = DEFAULT_POLICY) -> RecurrenceResult:
    history, diagnostics = prepare_history(events, as_of)
    groups = defaultdict(list)
    for event in history:
        groups[recurrence_identity(event, policy.identity_method)].append(event)
    series = tuple(infer_series(tuple(group), as_of, policy) for _, group in sorted(groups.items()))
    return RecurrenceResult(series, diagnostics)


def next_occurrence_date(series: RecurringSeries, after: date) -> date:
    cadence = series.cadence
    if cadence is None:
        raise ValueError('series has no supported cadence')
    if cadence.model == 'calendar_month':
        year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day if cadence.month_end else min(cadence.anchor_day, last_day))
    return after + timedelta(days=cadence.days)


def project_recurring_series(series: RecurringSeries, start_date: date, end_date: date,
                             policy: RecurrencePolicy | None = None) -> tuple[ProjectedOccurrence, ...]:
    """Inclusive window, after all observations; emits source predictions only.

    No scheduled income is merged or confirmed. Future amendments are deliberately
    external; provenance allows a later resolver to override the source prediction.
    """
    if policy is not None and policy != series.policy:
        raise ValueError('re-infer the series before changing its policy')
    if start_date < series.as_of or end_date < start_date:
        raise ValueError('projection must start at/after as_of, with end >= start')
    if not series.is_recurring or series.projected_amount is None:
        return ()
    result = []
    current = next_occurrence_date(series, series.dates[-1])
    while current <= end_date:
        if current >= start_date:
            result.append(ProjectedOccurrence(current, series.projected_amount, series.currency,
                                              series.direction, series.category, series.series_id,
                                              series.event_ids, series.confidence))
        current = next_occurrence_date(series, current)
    return tuple(result)
