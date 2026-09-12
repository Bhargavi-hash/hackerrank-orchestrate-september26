"""Expanding-window one-step prediction. Targets never enter training snapshots."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Iterable

from src.forecast.recurrence import (ARITHMETIC, decimal_median, infer_series,
    observation_date, prepare_history, project_recurring_series, recurrence_identity,
    is_recurrence_evidence)
from src.forecast.recurrence_models import RecurrencePolicy
from src.models.event import FinancialEvent


@dataclass(frozen=True)
class BacktestFold:
    policy_id: str
    user_id: str
    series_key: tuple[str, ...]
    target_event_id: str
    training_event_ids: tuple[str, ...]
    as_of: date
    actual_date: date
    actual_amount: Decimal
    currency: str
    category: str
    direction: str
    predicted_date: date | None
    predicted_amount: Decimal | None
    date_error: int | None
    amount_error: Decimal | None
    relative_error: Decimal | None
    confidence: str
    is_holdout: bool
    category_correct: bool | None
    direction_correct: bool | None
    training_descriptions: tuple[str, ...]
    target_description: str


def backtest_history(events: Iterable[FinancialEvent], cutoff: date,
                     policy: RecurrencePolicy, *,
                     prepared_snapshots: dict | None = None) -> tuple[tuple[BacktestFold, ...], dict[str, int]]:
    """Static identity defines targets; filtering/dedup/estimation use each prefix.

    For each group with >=4 distinct dated observations, hold out the last target;
    rolling folds start after three observations. as_of is the preceding observed
    date + 1, never the target date. Ambiguous lifecycle snapshots abstain.
    Series without enough observations are counted, not silently scored away.
    """
    events = tuple(events)
    groups = defaultdict(list)
    for e in events:
        if is_recurrence_evidence(e, cutoff):
            groups[recurrence_identity(e, policy.identity_method)].append(e)
    folds = []
    counts = {'historical_series': len(groups), 'eligible_series': 0,
              'excluded_short_series': 0, 'excluded_same_day_series': 0}
    # Caller may share this cache ONLY across policies on the identical input history.
    snapshots = prepared_snapshots if prepared_snapshots is not None else {}
    for key, group in sorted(groups.items()):
        group.sort(key=lambda e: (observation_date(e, policy), e.event_id))
        dates = [observation_date(e, policy) for e in group]
        if len(group) < 4:
            counts['excluded_short_series'] += 1
            continue
        if len(set(dates)) != len(dates):
            counts['excluded_same_day_series'] += 1
            continue
        counts['eligible_series'] += 1
        for index in range(3, len(group)):
            target = group[index]
            previous = group[index-1]
            as_of = max(previous.event_date, previous.settlement_date) + timedelta(days=1)
            # A target already known on the cutoff cannot be a future test outcome.
            if max(target.event_date, target.settlement_date) < as_of:
                continue
            if as_of not in snapshots:
                snapshots[as_of] = prepare_history(events, as_of)[0]
            prefix = tuple(e for e in snapshots[as_of]
                           if recurrence_identity(e, policy.identity_method) == key)
            series = infer_series(prefix, as_of, policy) if prefix else None
            projected = project_recurring_series(series, as_of, as_of + timedelta(days=366)) if series else ()
            prediction = projected[0] if projected else None
            predicted_date = prediction.date if prediction else None
            predicted_amount = prediction.amount if prediction else None
            with localcontext(ARITHMETIC):
                amount_error = abs(predicted_amount - target.amount) if prediction else None
                relative_error = amount_error / abs(target.amount) if prediction and target.amount else None
            folds.append(BacktestFold(
                policy.policy_id, target.user_id, key, target.event_id,
                series.event_ids if series else (), as_of, observation_date(target, policy),
                target.amount, target.currency, target.category, target.direction,
                predicted_date, predicted_amount,
                abs((predicted_date-observation_date(target, policy)).days) if prediction else None,
                amount_error, relative_error, series.confidence.value if series else 'insufficient',
                index == len(group)-1, prediction.category == target.category if prediction else None,
                prediction.direction == target.direction if prediction else None,
                tuple(sorted({e.description for e in prefix})), target.description,
            ))
    return tuple(folds), counts


def mean(values: Iterable[Decimal]) -> Decimal | None:
    values = tuple(values)
    with localcontext(ARITHMETIC):
        return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def summarize_folds(folds: Iterable[BacktestFold]) -> dict[str, object]:
    folds = tuple(folds)
    predicted = [f for f in folds if f.predicted_date is not None]
    relative = [f.relative_error for f in predicted if f.relative_error is not None]
    by_currency = defaultdict(list)
    for f in predicted:
        by_currency[f.currency].append(f.amount_error)
    return {
        'folds': len(folds), 'predicted': len(predicted), 'abstained': len(folds)-len(predicted),
        'date_mae_days': mean(Decimal(f.date_error) for f in predicted),
        'date_median_error_days': decimal_median(Decimal(f.date_error) for f in predicted) if predicted else None,
        'amount_mae_by_currency': {c: mean(v) for c, v in sorted(by_currency.items())},
        'amount_mean_relative_error': mean(relative),
        'amount_median_relative_error': decimal_median(relative) if relative else None,
        'zero_amount_targets': sum(f.actual_amount == 0 for f in folds),
        'category_correct': sum(f.category_correct is True for f in predicted),
        'direction_correct': sum(f.direction_correct is True for f in predicted),
    }
