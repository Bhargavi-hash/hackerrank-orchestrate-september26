"""Build validated joins once; grouped records retain source order."""
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, TypeVar
from src.models.event import FinancialEvent
from src.models.evidence import ImageRecord, Message
from src.models.plan import PaymentOption
from src.models.profile import FinancialProfile
from src.models.request import Request
from .loader import DataValidationError

if TYPE_CHECKING:
    from .loader import Dataset

T = TypeVar('T')


def _unique(rows: Iterable[T], key: Callable[[T], str]) -> dict[str, T]:
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result:
            raise DataValidationError(f'duplicate ID: {identity}')
        result[identity] = row
    return result


def _group(rows: Iterable[T], key: Callable[[T], str | None]) -> dict[str, tuple[T, ...]]:
    result = defaultdict(list)
    for row in rows:
        identity = key(row)
        if identity is not None:
            result[identity].append(row)
    return {identity: tuple(group) for identity, group in result.items()}


def build_linked_adjacency(events: dict[str, FinancialEvent]) -> dict[str, tuple[str, ...]]:
    """Undirected edges let traversal start at any lifecycle record."""
    adjacency: dict[str, set[str]] = {identity: set() for identity in events}
    for identity, event in events.items():
        linked = event.linked_event_id
        if linked is None:
            continue
        if linked not in events:
            raise DataValidationError(f'{identity}: unknown linked_event_id {linked}')
        if events[linked].user_id != event.user_id:
            raise DataValidationError(f'{identity}: linked event {linked} belongs to another user')
        adjacency[identity].add(linked)
        adjacency[linked].add(identity)
    return {identity: tuple(sorted(neighbors)) for identity, neighbors in adjacency.items()}


@dataclass(frozen=True)
class DataIndexes:
    profile_by_user_id: dict[str, FinancialProfile]
    requests_by_user_id: dict[str, tuple[Request, ...]]
    requests_by_request_id: dict[str, Request]
    events_by_user_id: dict[str, tuple[FinancialEvent, ...]]
    messages_by_user_id: dict[str, tuple[Message, ...]]
    images_by_user_id: dict[str, tuple[ImageRecord, ...]]
    images_by_related_event_id: dict[str, tuple[ImageRecord, ...]]
    payment_options_by_request_id: dict[str, tuple[PaymentOption, ...]]
    events_by_event_id: dict[str, FinancialEvent]
    messages_by_message_id: dict[str, Message]
    images_by_image_id: dict[str, ImageRecord]
    linked_event_adjacency: dict[str, tuple[str, ...]]


def build_indexes(data: 'Dataset') -> DataIndexes:
    profiles = _unique(data.profiles, lambda r: r.user_id)
    requests = _unique((*data.requests, *data.sample_requests), lambda r: r.request_id)
    events = _unique(data.events, lambda r: r.event_id)
    for row in (*requests.values(), *data.events, *data.messages, *data.images):
        if row.user_id not in profiles:
            raise DataValidationError(f'unknown user_id {row.user_id}')
    for row in (*data.messages, *data.images, *data.payment_options):
        if row.request_id is not None and row.request_id not in requests:
            raise DataValidationError(f'unknown request_id {row.request_id}')
        if isinstance(row, (Message, ImageRecord)):
            if row.request_id and requests[row.request_id].user_id != row.user_id:
                raise DataValidationError(f'{row.request_id}: evidence belongs to another user')
            if row.related_event_id:
                if row.related_event_id not in events:
                    raise DataValidationError(f'unknown related_event_id {row.related_event_id}')
                if events[row.related_event_id].user_id != row.user_id:
                    raise DataValidationError(f'{row.related_event_id}: evidence belongs to another user')
    return DataIndexes(
        profiles, _group(requests.values(), lambda r: r.user_id), requests,
        _group(data.events, lambda r: r.user_id), _group(data.messages, lambda r: r.user_id),
        _group(data.images, lambda r: r.user_id), _group(data.images, lambda r: r.related_event_id),
        _group(data.payment_options, lambda r: r.request_id), events,
        _unique(data.messages, lambda r: r.message_id), _unique(data.images, lambda r: r.image_id),
        build_linked_adjacency(events),
    )
