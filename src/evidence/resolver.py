"""Graph connectivity only; financial lifecycle interpretation is deferred."""
from src.data.indexes import DataIndexes
from src.data.loader import DataValidationError
from src.models.event import FinancialEvent


def resolve_linked_component(event_id: str, indexes: DataIndexes) -> tuple[FinancialEvent, ...]:
    visited: set[str] = set()
    pending = [event_id]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        if current not in indexes.events_by_event_id:
            raise DataValidationError(f'unknown event_id {current}')
        visited.add(current)
        pending.extend(indexes.linked_event_adjacency[current])
    return tuple(indexes.events_by_event_id[key] for key in sorted(visited))
