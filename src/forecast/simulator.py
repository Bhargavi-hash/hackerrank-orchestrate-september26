"""Apply supplied cashflows over 91 dates. No affordability or plan decisions."""
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal, localcontext
import json
from src.data.currency import CurrencyConverter
from src.models.profile import FinancialProfile
from .expenses import apply_spending_change
from .preparation import reconcile_projected_and_explicit_occurrences
from .simulation_models import (AppliedCashFlow, CandidatePayment, CashFlowOccurrence,
    DailyLedgerEntry, DEFAULT_TIMING_POLICY, SameDayOrder, SimulationResult,
    SpendingChangeEffect, TimingPolicy, require_money)
from .timeline import horizon_dates, select_fx_date


def check_safety(result: SimulationResult, minimum_balance: Decimal) -> bool:
    require_money(minimum_balance, 'minimum balance', signed=True)
    return result.complete and result.minimum_projected_balance >= minimum_balance


def _admissible(flow: CashFlowOccurrence) -> bool:
    # Defense at simulator boundary even if a caller bypasses preparation.
    if flow.direction == 'non_cash':
        return False
    if flow.status in {'cancelled', 'failed', 'unrealized'}:
        return False
    if flow.direction == 'credit' and flow.status == 'pending':
        return False
    if flow.status not in {'projected', 'pending', 'scheduled', 'settled', 'confirmed'}:
        raise ValueError(f'{flow.source_id}: unsupported occurrence status {flow.status}')
    if flow.status == 'scheduled' and flow.direction == 'credit':
        # Preparation certifies only this narrowly supported source description.
        from .recurrence import normalize_description
        if not (flow.category == 'salary' and flow.source_type == 'income'
                and normalize_description(flow.description) == 'next confirmed salary'):
            return False
    if flow.status == 'projected' and flow.confidence not in {'high', 'medium'}:
        return False
    return True


def simulate(profile: FinancialProfile, request_date: date,
             recurring_occurrences: tuple[CashFlowOccurrence, ...] = (),
             explicit_occurrences: tuple[CashFlowOccurrence, ...] = (),
             candidate_payments: tuple[CandidatePayment, ...] = (),
             spending_changes: tuple[SpendingChangeEffect, ...] = (),
             timing_policy: TimingPolicy = DEFAULT_TIMING_POLICY,
             *, currency_converter: CurrencyConverter | None = None,
             unresolved_sources: tuple[str, ...] = (), diagnostics: tuple[str, ...] = ()) -> SimulationResult:
    """Credits then aggregate debits within the normal cashflow block; candidates
    before/after that block. Safety includes opening and every block boundary.
    Candidate amounts are in home currency. Native flows convert at exact supplied
    dates, without cent rounding. No global state, history reconstruction or I/O.

    Overdue unsettled debits reserve on D. Other out-of-window cashflows are
    ignored; out-of-window candidate payments fail
    because silently truncating a proposed plan could give a misleading result.
    Incomplete inputs yield conditional known-flow minima and safe=False.
    """
    require_money(profile.current_available_balance, 'starting balance', signed=True)
    require_money(profile.minimum_balance_to_keep, 'minimum balance', signed=True)
    days = horizon_dates(request_date)
    payments = defaultdict(list)
    for payment in candidate_payments:
        if not request_date <= payment.date <= days[-1]:
            raise ValueError(f'{payment.source}: candidate outside simulation horizon')
        payments[payment.date].append(payment)
    candidates = [flow for flow in (*recurring_occurrences, *explicit_occurrences) if _admissible(flow)]
    if any(flow.user_id != profile.user_id for flow in candidates):
        raise ValueError('occurrence belongs to another user')
    # A caller may supply an overdue unsettled debit directly, bypassing preparation.
    candidates = [replace(flow,date=request_date) if flow.direction == 'debit'
                  and flow.status in {'pending','scheduled'} and flow.date < request_date
                  else flow for flow in candidates]
    # Historical settled records must never be replayed, including on the snapshot date.
    candidates = [flow for flow in candidates if request_date <= flow.date <= days[-1]
                  and not (flow.status == 'settled' and flow.date <= request_date)]
    synthetic = [f for f in candidates if f.status == 'projected']
    concrete = [f for f in candidates if f.status != 'projected']
    flows = reconcile_projected_and_explicit_occurrences(synthetic, concrete)
    keys = [(f.source_id, f.date) for f in flows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate occurrence source/date')
    matched_changes = set()
    by_date, effects = defaultdict(list), defaultdict(list)
    money_values = [profile.current_available_balance, profile.minimum_balance_to_keep]
    for flow in flows:
        matches = [(i, c) for i, c in enumerate(spending_changes)
                   if flow.date >= c.from_date and c.target_id in
                   (flow.source_id, flow.series_id, *flow.source_event_ids)]
        if len(matches) > 1:
            raise ValueError(f'{flow.source_id}: overlapping spending changes')
        if matches:
            i, change = matches[0]
            flow, effect = apply_spending_change(flow, change, profile)
            effects[flow.date].append(effect)
            matched_changes.add(i)
        rate_date = select_fx_date(flow, timing_policy)
        if flow.currency == profile.home_currency:
            amount = flow.amount
        elif currency_converter is None:
            raise ValueError(f'{flow.source_id}: currency converter required')
        else:
            amount = currency_converter.convert_amount(flow.amount, flow.currency, profile.home_currency, rate_date)
        by_date[flow.date].append(AppliedCashFlow(flow, amount, rate_date))
        money_values.append(amount)
    if len(matched_changes) != len(spending_changes):
        raise ValueError('spending change has no matching occurrence within horizon')
    money_values.extend(p.amount for p in candidate_payments)
    # Precision sufficient for exact additions/subtractions across all input scales,
    # even under a hostile caller Decimal context. FX multiplication is also exact.
    least_exponent = min(v.as_tuple().exponent for v in money_values)
    most_digits = max(v.adjusted() for v in money_values)
    precision = max(28, most_digits - least_exponent + len(str(len(money_values))) + 3)
    entries = []
    with localcontext() as context:
        context.prec = precision
        balance = profile.current_available_balance
        minimum = balance
        minimum_day = request_date
        first_violation = None
        for day in days:
            opening = balance
            credits = tuple(f for f in by_date[day] if f.occurrence.direction == 'credit')
            debits = tuple(f for f in by_date[day] if f.occurrence.direction == 'debit')
            day_payments = tuple(sorted(payments[day], key=lambda p: (p.source, p.amount)))
            payment_total = sum((p.amount for p in day_payments), Decimal('0'))
            checkpoints = [('opening', balance)]
            if timing_policy.same_day_order == SameDayOrder.CANDIDATE_BEFORE_CASHFLOWS:
                balance -= payment_total
                checkpoints.append(('candidate_payment', balance))
            balance += sum((f.home_amount for f in credits), Decimal('0'))
            checkpoints.append(('credits', balance))
            balance -= sum((f.home_amount for f in debits), Decimal('0'))
            checkpoints.append(('debits', balance))
            if timing_policy.same_day_order == SameDayOrder.CASHFLOWS_BEFORE_CANDIDATE:
                balance -= payment_total
                checkpoints.append(('candidate_payment', balance))
            day_minimum = min(value for _, value in checkpoints)
            safe = day_minimum >= profile.minimum_balance_to_keep
            if day_minimum < minimum:
                minimum, minimum_day = day_minimum, day
            if not safe and first_violation is None:
                first_violation = day
            entries.append(DailyLedgerEntry(day, opening, credits, debits, day_payments,
                tuple(effects[day]), balance, profile.minimum_balance_to_keep,
                day_minimum, safe, tuple(checkpoints)))
    complete = not unresolved_sources
    return SimulationResult(request_date, days[-1], tuple(entries), minimum, minimum_day,
        complete and first_violation is None, first_violation, complete,
        tuple(sorted(unresolved_sources)), tuple(sorted(diagnostics)))


def trace_json(result: SimulationResult) -> str:
    """Opt-in debug serialization; original native money and source IDs retained."""
    def encode(value):
        if isinstance(value, (Decimal, date)):
            return str(value)
        raise TypeError(f'cannot encode {type(value)}')
    return json.dumps(asdict(result), default=encode, indent=2, sort_keys=True) + '\n'
