"""Capacity facts and immutable reuse of a prepared, unchanged forecast."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.data.currency import CurrencyConverter
from src.forecast.simulation_models import PreparedForecast, SimulationResult
from src.models.profile import FinancialProfile


@dataclass(frozen=True)
class CapacityContext:
    """Construct with prepare_capacity; reused across all payment-date probes."""
    profile: FinancialProfile
    request_date: date
    forecast: PreparedForecast
    currency_converter: CurrencyConverter | None
    baseline: SimulationResult


@dataclass(frozen=True)
class CapacityProbe:
    date: date
    amount: Decimal
    safe: bool
    minimum_projected_balance: Decimal
    minimum_projected_balance_date: date
    first_violation_date: date | None


@dataclass(frozen=True)
class CapacityResult:
    amount_safe_to_pay: Decimal
    earliest_date_for_full_payment: date | None
    baseline_complete: bool
    baseline_safe: bool
    minimum_headroom: Decimal | None
    all_checkpoint_headroom: Decimal | None
    safe_amount_verified: bool
    maximality_verified: bool | None
    safe_amount_probe: CapacityProbe | None
    next_cent_probe: CapacityProbe | None
    full_payment_probes: tuple[CapacityProbe, ...]
    diagnostics: tuple[str, ...]
