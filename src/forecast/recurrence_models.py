"""Immutable recurrence inputs, diagnostics and source predictions."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class RecurrenceConfidence(str, Enum):
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    INSUFFICIENT = 'insufficient'


@dataclass(frozen=True)
class ConfidenceThresholds:
    minimum_observations: int = 3
    high_observations: int = 4
    high_interval_deviation: Decimal = Decimal('0.10')
    maximum_interval_deviation: Decimal = Decimal('0.35')
    high_amount_cv: Decimal = Decimal('0.35')
    maximum_stale_cycles: Decimal = Decimal('2')

    def __post_init__(self) -> None:
        if self.minimum_observations < 3 or self.high_observations < self.minimum_observations:
            raise ValueError('require at least three observations, high >= minimum')
        if not (0 <= self.high_interval_deviation <= self.maximum_interval_deviation):
            raise ValueError('invalid interval thresholds')
        if self.high_amount_cv < 0 or self.maximum_stale_cycles <= 0:
            raise ValueError('invalid amount/recency thresholds')


@dataclass(frozen=True)
class RecurrencePolicy:
    policy_id: str = 'amount_mean_last_5'
    identity_method: str = 'category'
    cadence_method: str = 'calendar_aware'
    amount_method: str = 'mean_last_5'
    spend_rate_method: str = 'none'
    date_source: str = 'event_date'
    thresholds: ConfidenceThresholds = ConfidenceThresholds()

    def __post_init__(self) -> None:
        options = {
            'identity_method': {'exact', 'category', 'family'},
            'cadence_method': {'median', 'recent_median', 'mode', 'calendar_aware'},
            'amount_method': {'latest', 'mean_last_3', 'median_last_3', 'mean_last_5', 'median_last_5', 'max_last_3'},
            'spend_rate_method': {'none', 'rolling_28'},
            'date_source': {'event_date', 'settlement_date'},
        }
        for field, allowed in options.items():
            if getattr(self, field) not in allowed:
                raise ValueError(f'{field} must be one of {sorted(allowed)}')


# Provisional default; evidence and selection strength documented by calibration.
DEFAULT_POLICY = RecurrencePolicy()


@dataclass(frozen=True)
class Cadence:
    model: str
    days: int | None
    anchor_day: int | None = None
    month_end: bool = False


@dataclass(frozen=True)
class RecurrenceDiagnostics:
    observation_count: int
    median_interval_days: Decimal | None
    interval_mad: Decimal | None
    maximum_interval_deviation: Decimal | None
    amount_cv: Decimal | None
    description_count: int
    stale_cycles: Decimal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecurringSeries:
    user_id: str
    series_id: str
    identity_key: tuple[str, ...]
    event_ids: tuple[str, ...]
    event_type: str
    category: str
    normalized_description_family: str
    direction: str
    currency: str
    dates: tuple[date, ...]
    amounts: tuple[Decimal, ...]
    cadence: Cadence | None
    projected_amount: Decimal | None
    amount_model: str
    confidence: RecurrenceConfidence
    diagnostics: RecurrenceDiagnostics
    as_of: date
    policy: RecurrencePolicy

    @property
    def is_recurring(self) -> bool:
        return self.confidence in {RecurrenceConfidence.HIGH, RecurrenceConfidence.MEDIUM}


@dataclass(frozen=True)
class ProjectedOccurrence:
    date: date
    amount: Decimal
    currency: str
    direction: str
    category: str
    source_series_id: str
    source_event_ids: tuple[str, ...]
    confidence: RecurrenceConfidence
    provenance: str = 'historical_recurrence_prediction_not_confirmation'


@dataclass(frozen=True)
class HistoryDiagnostic:
    event_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class RecurrenceResult:
    series: tuple[RecurringSeries, ...]
    history_diagnostics: tuple[HistoryDiagnostic, ...]
