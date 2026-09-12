"""Immutable original CSV cells accompany every normalized record."""
from dataclasses import dataclass, field
from typing import Mapping
from types import MappingProxyType


@dataclass(frozen=True, kw_only=True)
class SourceRecord:
    raw: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), repr=False, compare=False)
