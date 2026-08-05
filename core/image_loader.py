"""Directory scanning for supported image files (Qt-free)."""
from __future__ import annotations

import logging
from pathlib import Path

from app_info import SUPPORTED_INPUT_EXTENSIONS

logger = logging.getLogger(__name__)


def is_supported_image(path: Path) -> bool:
    """True if ``path`` has a supported image extension (case-insensitive)."""
    return path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS


def scan_directory(directory: Path) -> list[Path]:
    """Return all supported images directly inside ``directory``, sorted
    case-insensitively by file name (Explorer-like order).

    Non-recursive on purpose: the tool works on one folder at a time and
    recursing into e.g. a Downloads folder tree would be surprising.
    Returns an empty list for missing/unreadable directories.
    """
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        logger.warning("Cannot scan %s: %s", directory, exc)
        return []
    images = [p for p in entries if p.is_file() and is_supported_image(p)]
    images.sort(key=lambda p: p.name.lower())
    logger.info("Scanned %s: %d images", directory, len(images))
    return images


def filter_supported(paths: list[Path]) -> list[Path]:
    """Keep only existing, supported image files (for drag & drop)."""
    return [p for p in paths if p.is_file() and is_supported_image(p)]
