"""Data model for a single image in the working set (Qt-free)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class ImageStatus(Enum):
    """Processing state shown as a colored badge on the thumbnail."""

    UNPROCESSED = auto()   # gray
    PROCESSING = auto()    # blue
    EXPORTED = auto()      # green
    FAILED = auto()        # red


@dataclass
class ImageItem:
    """One image file plus its per-session processing state."""

    path: Path
    status: ImageStatus = field(default=ImageStatus.UNPROCESSED)

    @property
    def name(self) -> str:
        return self.path.name
