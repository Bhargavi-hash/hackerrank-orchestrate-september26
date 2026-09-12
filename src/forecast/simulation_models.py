"""Immutable simulator inputs/results. Monetary values are never coerced."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


def require_money(value: Decimal, name: str, *, signed: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f'{name} must be a finite Decimal')
    if not signed and value < 0:
        raise ValueError(f'{name} must be nonnegative')


class SameDayOrder(str, Enum):
    CASHFLOWS_BEFORE_CANDIDATE = 'cashflows_before_candidate'
    CANDIDATE_BEFORE_CASHFLOWS = 'candidate_before_cashflows'


class FutureEventDateSource(str, Enum):
    EVENT_DATE = 'event_date'
    SETTLEMENT_DATE = 'settlement_date'


class FXDatePolicy(str, Enum):
    EXACT_CASH_DATE = 'exact_cash_date'


@dataclass(frozen=True)
class TimingPolicy:
    same_day_order: SameDayOrder = SameDayOrder.CASHFLOWS_BEFORE_CANDIDATE
    future_event_date_source: FutureEventDateSource = FutureEventDateSource.SETTLEMENT_DATE
    fx_date_policy: FXDatePolicy = FXDatePolicy.EXACT_CASH_DATE

    def __post_init__(self) -> None:
        for value, kind in ((self.same_day_order, SameDayOrder),
                            (self.future_event_date_source, FutureEventDateSource),
                            (self.fx_date_policy, FXDatePolicy)):
            if not isinstance(value, kind):
                raise ValueError(f'expected {kind.__name__}, got {value!r}')


DEFAULT_TIMING_POLICY = TimingPolicy()


@dataclass(frozen=True)
class CashFlowOccurrence:
    source_id: str
    user_id: str
    date: date
    amount: Decimal
    currency: str
    direction: str
    category: str
    provenance: str
    status: str
    source_type: str = 'expense'
    confidence: str | None = None
    series_id: str | None = None
    source_event_ids: tuple[str, ...] = ()
    description: str = ''
    flexibility: str = 'fixed'
    minimum_allowed_amount: Decimal | None = None
    # Original settlement date remains the required FX date even in timing experiments.
    fx_date: date | None = None

    def __post_init__(self) -> None:
        require_money(self.amount, 'occurrence amount')
        if self.direction not in {'credit', 'debit', 'non_cash'}:
            raise ValueError(f'unknown direction {self.direction}')
        if not self.source_id or not self.user_id or not self.currency or not self.provenance:
            raise ValueError('occurrences require source, user, currency and provenance')
        if self.minimum_allowed_amount is not None:
            require_money(self.minimum_allowed_amount, 'minimum_allowed_amount')


@dataclass(frozen=True)
class CandidatePayment:
    date: date
    amount: Decimal
    source: str
    provenance: str = field(default='candidate_payment', init=False)

    def __post_init__(self) -> None:
        require_money(self.amount, 'candidate amount')
        if not self.source:
            raise ValueError('candidate source is required')


@dataclass(frozen=True)
class SpendingChangeEffect:
    """External instruction in target currency; no savings credited independently."""
    target_id: str
    from_date: date
    operation: str
    new_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.operation not in {'stop', 'reduce_to'}:
            raise ValueError('spending operation must be stop or reduce_to')
        if self.operation == 'reduce_to':
            require_money(self.new_amount, 'reduced amount')
        elif self.new_amount is not None:
            raise ValueError('stop does not take an amount')


@dataclass(frozen=True)
class AppliedSpendingChange:
    target_id: str
    source_id: str
    operation: str
    original_amount: Decimal
    new_amount: Decimal
    currency: str
    provenance: str = 'spending_change'


@dataclass(frozen=True)
class AppliedCashFlow:
    occurrence: CashFlowOccurrence
    home_amount: Decimal
    rate_date: date


@dataclass(frozen=True)
class DailyLedgerEntry:
    date: date
    opening_balance: Decimal
    credits: tuple[AppliedCashFlow, ...]
    debits: tuple[AppliedCashFlow, ...]
    candidate_payments: tuple[CandidatePayment, ...]
    spending_change_effects: tuple[AppliedSpendingChange, ...]
    closing_balance: Decimal
    minimum_required: Decimal
    minimum_balance: Decimal
    safe: bool
    checkpoints: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class SimulationResult:
    start_date: date
    end_date: date
    entries: tuple[DailyLedgerEntry, ...]
    minimum_projected_balance: Decimal
    minimum_projected_balance_date: date
    safe: bool
    first_violation_date: date | None
    complete: bool
    unresolved_sources: tuple[str, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class PreparedForecast:
    recurring_occurrences: tuple[CashFlowOccurrence, ...]
    explicit_occurrences: tuple[CashFlowOccurrence, ...]
    unresolved_sources: tuple[str, ...]
    diagnostics: tuple[str, ...]
    ignored_pending_credit_count: int
