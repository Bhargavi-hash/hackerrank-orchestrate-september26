"""Exact supplied date/direction only. No inverses, interpolation or fallback."""
from datetime import date
from decimal import Decimal, localcontext
from typing import Iterable
from src.models.currency import ExchangeRate
from .loader import DataValidationError


class MissingExchangeRateError(LookupError):
    pass


class CurrencyConverter:
    def __init__(self, rates: Iterable[ExchangeRate]) -> None:
        self._rates: dict[tuple[date, str, str], Decimal] = {}
        for row in rates:
            key = (row.rate_date, row.from_currency, row.to_currency)
            if key in self._rates:
                raise DataValidationError(f'duplicate FX key {key}')
            if row.rate is None or not row.rate.is_finite() or row.rate <= 0:
                raise DataValidationError(f'{key}: FX rate must be present, finite and positive')
            self._rates[key] = row.rate

    def select_rate(self, from_currency: str, to_currency: str, rate_date: date) -> Decimal:
        """Exact date policy; future recurrence FX semantics remain unresolved."""
        try:
            return self._rates[(rate_date, from_currency, to_currency)]
        except KeyError as exc:
            raise MissingExchangeRateError(f'No supplied FX rate: {rate_date} {from_currency}->{to_currency}') from exc

    def convert_amount(self, amount: Decimal, from_currency: str, to_currency: str, rate_date: date) -> Decimal:
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise TypeError('amount must be a finite Decimal')
        if from_currency == to_currency:
            return amount
        rate = self.select_rate(from_currency, to_currency, rate_date)
        # Exact multiplication, independent of caller precision; currency rounding is deferred.
        with localcontext() as context:
            context.prec = max(28, len(amount.as_tuple().digits) + len(rate.as_tuple().digits))
            return amount * rate
