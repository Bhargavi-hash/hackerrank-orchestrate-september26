from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from .base import SourceRecord


@dataclass(frozen=True)
class Message(SourceRecord):
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageRecord(SourceRecord):
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None

    def image_path(self, dataset_root: Path) -> Path:
        return dataset_root / "media" / "images" / f"{self.image_id}.png"
