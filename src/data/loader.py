"""Central schema validation and typed loading; never interpret evidence text."""
import csv
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar, get_type_hints

from src.config import dataset_root
from src.models.base import SourceRecord
from src.models.currency import ExchangeRate
from src.models.event import FinancialEvent
from src.models.evidence import ImageRecord, Message
from src.models.plan import PaymentOption
from src.models.profile import FinancialProfile
from src.models.request import OutputTemplateRow, Request, SampleRequest
from .parsers import (parse_bool, parse_collection, parse_date, parse_datetime,
                      parse_id, parse_int, parse_money)


class DataValidationError(ValueError):
    """A source file, column, row, or relationship violates the input contract."""


MODEL_FILES = {
    'requests.csv': Request,
    'sample_requests.csv': SampleRequest,
    'financial_profiles.csv': FinancialProfile,
    'financial_events.csv': FinancialEvent,
    'messages.csv': Message,
    'images.csv': ImageRecord,
    'request_payment_options.csv': PaymentOption,
    'exchange_rates.csv': ExchangeRate,
    'output.csv': OutputTemplateRow,
}
OUTPUT_COLUMNS = tuple(f.name for f in fields(OutputTemplateRow) if f.name != 'raw')
ENUMS = {
    'direction': {'debit', 'credit', 'non_cash'},
    'status': {'settled', 'pending', 'scheduled', 'cancelled', 'failed', 'unrealized'},
    'flexibility': {'fixed', 'reducible', 'stoppable', 'reducible_or_stoppable'},
    'payment_method': {'full_payment', 'installments'},
}
T = TypeVar('T', bound=SourceRecord)


def _parse(value: str, name: str, annotation: object) -> object:
    if name.endswith('_id'):
        result = parse_id(value)
    elif annotation in (Decimal, Decimal | None):
        result = parse_money(value)
    elif annotation in (date, date | None):
        result = parse_date(value.strip())
    elif annotation is datetime:
        result = parse_datetime(value.strip())
    elif annotation is bool:
        result = parse_bool(value)
    elif annotation in (int, int | None):
        result = parse_int(value.strip())
    elif annotation == tuple[str, ...]:
        result = parse_collection(value)
    elif annotation == frozenset[str]:
        result = frozenset(parse_collection(value))
    else:
        result = value if value.strip() else None
    if result is None and annotation not in (str | None, date | None, int | None, Decimal | None):
        raise ValueError('required value is blank')
    if name in ENUMS and result not in ENUMS[name]:
        raise ValueError(f'expected one of {sorted(ENUMS[name])}')
    return result


def _load(root: str | Path | None, filename: str, model: type[T]) -> tuple[T, ...]:
    path = dataset_root(root) / filename
    hints = get_type_hints(model)
    columns = tuple(f.name for f in fields(model) if f.name != 'raw')
    records = []
    seen = set()
    try:
        with path.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle, strict=True)
            header = reader.fieldnames or []
            missing = set(columns) - set(header)
            if missing:
                raise DataValidationError(f'{path}: missing required columns: {sorted(missing)}')
            if len(set(header)) != len(header):
                raise DataValidationError(f'{path}: duplicate column names')
            if filename == 'output.csv' and tuple(header) != OUTPUT_COLUMNS:
                raise DataValidationError(f'{path}: output template columns must match exact order')
            for row in reader:
                context = f'{path}: row {reader.line_num}'
                if None in row or any(v is None for v in row.values()):
                    raise DataValidationError(f'{context}: row width does not match header')
                values = {}
                for name in columns:
                    try:
                        values[name] = _parse(row[name], name, hints[name])
                    except (ValueError, TypeError) as exc:
                        raise DataValidationError(f'{context}, column {name}: {exc}') from exc
                key = (values['rate_date'], values['from_currency'], values['to_currency']) if model is ExchangeRate else values[columns[0]]
                if key in seen:
                    raise DataValidationError(f'{context}: duplicate key {key!r}')
                seen.add(key)
                records.append(model(**values, raw=MappingProxyType(dict(row))))
    except (OSError, csv.Error) as exc:
        raise DataValidationError(f'{path}: {exc}') from exc
    return tuple(records)


def load_requests(root: str | Path | None = None) -> tuple[Request, ...]:
    return _load(root, 'requests.csv', Request)


def load_sample_requests(root: str | Path | None = None) -> tuple[SampleRequest, ...]:
    return _load(root, 'sample_requests.csv', SampleRequest)


def load_profiles(root: str | Path | None = None) -> tuple[FinancialProfile, ...]:
    return _load(root, 'financial_profiles.csv', FinancialProfile)


def load_events(root: str | Path | None = None) -> tuple[FinancialEvent, ...]:
    return _load(root, 'financial_events.csv', FinancialEvent)


def load_messages(root: str | Path | None = None) -> tuple[Message, ...]:
    return _load(root, 'messages.csv', Message)


def load_images(root: str | Path | None = None) -> tuple[ImageRecord, ...]:
    return _load(root, 'images.csv', ImageRecord)


def load_payment_options(root: str | Path | None = None) -> tuple[PaymentOption, ...]:
    return _load(root, 'request_payment_options.csv', PaymentOption)


def load_exchange_rates(root: str | Path | None = None) -> tuple[ExchangeRate, ...]:
    return _load(root, 'exchange_rates.csv', ExchangeRate)


def load_output_template(root: str | Path | None = None) -> tuple[OutputTemplateRow, ...]:
    return _load(root, 'output.csv', OutputTemplateRow)


@dataclass(frozen=True)
class Dataset:
    root: Path
    requests: tuple[Request, ...]
    sample_requests: tuple[SampleRequest, ...]
    profiles: tuple[FinancialProfile, ...]
    events: tuple[FinancialEvent, ...]
    messages: tuple[Message, ...]
    images: tuple[ImageRecord, ...]
    payment_options: tuple[PaymentOption, ...]
    exchange_rates: tuple[ExchangeRate, ...]
    output_template: tuple[OutputTemplateRow, ...]


def load_all_data(root: str | Path | None = None) -> Dataset:
    root = dataset_root(root)
    data = Dataset(root, load_requests(root), load_sample_requests(root),
                   load_profiles(root), load_events(root), load_messages(root),
                   load_images(root), load_payment_options(root),
                   load_exchange_rates(root), load_output_template(root))
    # Local import avoids coupling individual CSV loaders to index construction.
    from .indexes import build_indexes
    build_indexes(data)  # Validate all joins before returning a usable dataset.
    template_ids = {r.request_id for r in data.output_template}
    if template_ids != {r.request_id for r in data.requests}:
        raise DataValidationError('output.csv: template request IDs differ from requests.csv')
    if any(any(value.strip() for key, value in row.raw.items() if key != 'request_id')
           for row in data.output_template):
        raise DataValidationError('output.csv: expected a blank input template')
    return data
