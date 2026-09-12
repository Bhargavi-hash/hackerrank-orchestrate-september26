"""Central horizon, aggregation order and exact dataset FX date selection."""
from datetime import date, timedelta
from .simulation_models import CashFlowOccurrence, FXDatePolicy, TimingPolicy

HORIZON_DAYS = 90


def horizon_dates(start: date) -> tuple[date, ...]:
    """D through D+90 inclusive: 91 calendar dates."""
    return tuple(start + timedelta(days=offset) for offset in range(HORIZON_DAYS + 1))


def occurrence_order(flow: CashFlowOccurrence) -> tuple:
    return (flow.date, flow.source_id, flow.provenance, flow.direction,
            flow.currency, flow.amount)


def select_fx_date(flow: CashFlowOccurrence, policy: TimingPolicy) -> date:
    """Explicit events retain settlement FX; recurrence uses its projected date.

    Exact-date only. A timing flag does not change exchange-rate valuation.
    Missing future rates fail, never interpolate or fetch rates.
    """
    if policy.fx_date_policy != FXDatePolicy.EXACT_CASH_DATE:
        raise ValueError('unsupported FX date policy')
    return flow.fx_date or flow.date
