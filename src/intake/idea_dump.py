"""Raw user idea capture for the first stage of muchanipo."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class IdeaDump:
    raw_text: str
    source: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("IdeaDump.raw_text must not be empty")
