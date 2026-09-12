import unittest
from datetime import date
from decimal import Decimal, localcontext
from src.data.currency import CurrencyConverter, MissingExchangeRateError
from src.data.loader import DataValidationError
from src.models.currency import ExchangeRate
from tests.fixtures import dataset


class CurrencyTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 1, 1)
        self.rate = ExchangeRate(self.day, 'EUR', 'USD', Decimal('1.25'))
        self.converter = CurrencyConverter([self.rate])

    def test_fx_same_currency(self):
        amount = Decimal('12.30')
        self.assertIs(self.converter.convert_amount(amount, 'INR', 'INR', self.day), amount)

    def test_fx_conversion(self):
        self.assertEqual(self.converter.convert_amount(Decimal('12.30'), 'EUR', 'USD', self.day), Decimal('15.3750'))
        converter = CurrencyConverter(dataset().exchange_rates)
        for rate in dataset().exchange_rates:
            self.assertEqual(converter.convert_amount(Decimal('2'), rate.from_currency, rate.to_currency, rate.rate_date), rate.rate * 2)

    def test_fx_missing_rate_behavior(self):
        for source, target, day in [('USD', 'EUR', self.day), ('EUR', 'USD', date(2026, 1, 2))]:
            with self.assertRaisesRegex(MissingExchangeRateError, 'No supplied FX rate'):
                self.converter.convert_amount(Decimal('1'), source, target, day)

    def test_fx_rejects_duplicate_invalid_rates(self):
        with self.assertRaises(DataValidationError):
            CurrencyConverter([self.rate, self.rate])
        for rate in [None, Decimal('0'), Decimal('-1'), Decimal('NaN')]:
            with self.assertRaises(DataValidationError):
                CurrencyConverter([ExchangeRate(self.day, 'EUR', 'USD', rate)])

    def test_fx_exact_despite_low_context_precision(self):
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.converter.convert_amount(Decimal('123.45'), 'EUR', 'USD', self.day), Decimal('154.3125'))

    def test_fx_rejects_binary_float(self):
        with self.assertRaises(TypeError):
            self.converter.convert_amount(1.2, 'EUR', 'USD', self.day)
