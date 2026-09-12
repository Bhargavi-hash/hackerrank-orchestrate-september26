"""Capacity only: analytical headroom and sequential request-centered date search.

No preference/deadline filtering, optional spending changes or recommendations.
All probes use the unchanged Phase 3 default timing and the same prepared inputs.
"""
from datetime import date
from decimal import Context, Decimal, ROUND_FLOOR, localcontext

from src.data.currency import CurrencyConverter
from src.forecast.simulation_models import (CandidatePayment, DEFAULT_TIMING_POLICY,
    PreparedForecast, SimulationResult, require_money)
from src.forecast.simulator import check_safety, simulate
from src.forecast.timeline import horizon_dates
from src.models.profile import FinancialProfile
from .capacity_models import CapacityContext, CapacityProbe, CapacityResult

PAYMENT_UNIT = Decimal('0.01')


class CapacityVerificationError(RuntimeError):
    """Analytical capacity and independent simulation disagree: do not publish."""


def _arithmetic(*values: Decimal) -> Context:
    # Exact subtraction at every input scale, independent of caller context.
    precision = max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 4
    return Context(prec=max(28, precision), rounding=ROUND_FLOOR)


def prepare_capacity(profile: FinancialProfile, request_date: date,
                     forecast: PreparedForecast,
                     currency_converter: CurrencyConverter | None = None) -> CapacityContext:
    """Build baseline once; callers prepare recurrence once before this function."""
    baseline = simulate(profile, request_date, forecast.recurring_occurrences,
        forecast.explicit_occurrences, timing_policy=DEFAULT_TIMING_POLICY,
        currency_converter=currency_converter, unresolved_sources=forecast.unresolved_sources,
        diagnostics=forecast.diagnostics)
    return CapacityContext(profile, request_date, forecast, currency_converter, baseline)


def minimum_payment_headroom(baseline: SimulationResult, minimum_balance: Decimal) -> Decimal:
    """Minimum over checkpoints affected by a payment on the request date.

    Read the simulator's actual ordered checkpoint stream, starting at its
    candidate_payment marker on D. Earlier checkpoints are NOT shifted by payment;
    baseline safety must separately hold there (and everywhere else).
    This avoids both double-defining ordering and counting future credit as cash
    before the payment. See architecture §25's approved Phase 4 clarification.
    """
    require_money(minimum_balance, 'minimum balance', signed=True)
    if not baseline.entries or baseline.entries[0].date != baseline.start_date:
        raise ValueError('baseline must include its request-date ledger entry')
    affected = []
    reached_payment = False
    for entry in baseline.entries:
        if entry.candidate_payments or entry.spending_change_effects:
            raise ValueError('capacity requires an unchanged baseline without candidate payments')
        for name, balance in entry.checkpoints:
            if entry.date == baseline.start_date and name == 'candidate_payment':
                reached_payment = True
            if reached_payment:
                affected.append(balance)
    if not reached_payment:
        raise ValueError('baseline lacks simulator candidate-payment checkpoint')
    minimum = min(affected)
    with localcontext(_arithmetic(minimum, minimum_balance)):
        return minimum - minimum_balance


def _probe(context: CapacityContext, amount: Decimal, day: date) -> CapacityProbe:
    forecast = context.forecast
    result = simulate(context.profile, context.request_date,
        forecast.recurring_occurrences, forecast.explicit_occurrences,
        candidate_payments=(CandidatePayment(day, amount, 'capacity_verification'),),
        timing_policy=DEFAULT_TIMING_POLICY, currency_converter=context.currency_converter,
        unresolved_sources=forecast.unresolved_sources, diagnostics=forecast.diagnostics)
    return CapacityProbe(day, amount, check_safety(result, context.profile.minimum_balance_to_keep),
        result.minimum_projected_balance, result.minimum_projected_balance_date, result.first_violation_date)


def _safe_amount(context: CapacityContext, requested_amount: Decimal):
    require_money(requested_amount, 'requested amount')
    baseline = context.baseline
    if not baseline.complete:
        return Decimal('0.00'), None, None, None, None
    headroom = minimum_payment_headroom(baseline, context.profile.minimum_balance_to_keep)
    with localcontext(_arithmetic(headroom, requested_amount, PAYMENT_UNIT)):
        amount = min(requested_amount, max(Decimal('0'), headroom)).quantize(PAYMENT_UNIT, rounding=ROUND_FLOOR)
        # Payments cannot repair an existing baseline violation, including a
        # request-day checkpoint before the cashflows/payment execution block.
        if not check_safety(baseline, context.profile.minimum_balance_to_keep):
            amount = Decimal('0.00')
        next_cent = amount + PAYMENT_UNIT
    verified = _probe(context, amount, context.request_date)
    if amount > 0 and not verified.safe:
        raise CapacityVerificationError('positive analytical safe amount failed simulator verification')
    maximality = _probe(context, next_cent, context.request_date) if next_cent <= requested_amount else None
    if maximality is not None and maximality.safe:
        raise CapacityVerificationError('one cent above analytical capacity is still safe')
    return amount, headroom, verified, maximality, (not maximality.safe if maximality else None)


def calculate_safe_amount(context: CapacityContext, requested_amount: Decimal) -> Decimal:
    """Cent-grid maximum, rounded down, capped at request; independently verified."""
    return _safe_amount(context, requested_amount)[0]


def _search_full_payment_dates(context: CapacityContext, requested_amount: Decimal):
    require_money(requested_amount, 'requested amount')
    if not context.baseline.complete:
        return None, ()
    probes = []
    # Intentionally sequential, including non-cashflow dates. Do not roll the
    # forecast forward or use deadlines/preferences to truncate this range.
    for day in horizon_dates(context.request_date):
        probe = _probe(context, requested_amount, day)
        probes.append(probe)
        if probe.safe:
            return day, tuple(probes)
    return None, tuple(probes)


def find_earliest_full_payment_date(context: CapacityContext, requested_amount: Decimal) -> date | None:
    return _search_full_payment_dates(context, requested_amount)[0]


def evaluate_capacity(context: CapacityContext, requested_amount: Decimal) -> CapacityResult:
    amount, headroom, verification, next_cent, maximality = _safe_amount(context, requested_amount)
    earliest, probes = _search_full_payment_dates(context, requested_amount)
    baseline = context.baseline
    diagnostics = list(baseline.diagnostics)
    all_headroom = None
    if baseline.complete:
        with localcontext(_arithmetic(baseline.minimum_projected_balance, context.profile.minimum_balance_to_keep)):
            all_headroom = baseline.minimum_projected_balance - context.profile.minimum_balance_to_keep
        if not baseline.safe:
            diagnostics.append('baseline already violates floor; nonnegative payment cannot repair it')
        if headroom != all_headroom:
            diagnostics.append('payment-affected headroom differs from all-checkpoint headroom; earlier checkpoints are unchanged')
    else:
        diagnostics.extend(baseline.unresolved_sources)
        diagnostics.append('incomplete forecast: conservative terminal capacity 0, no provable full-payment date')
    if requested_amount.as_tuple().exponent < -2:
        diagnostics.append('safe amount uses 0.01 grid; full-payment probes preserve exact requested amount')
    return CapacityResult(amount, earliest, baseline.complete, baseline.safe, headroom, all_headroom,
        verification.safe if verification else False, maximality, verification, next_cent,
        probes, tuple(sorted(set(diagnostics))))
