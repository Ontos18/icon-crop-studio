"""Qt bridge running exports on a thread pool.

Exports run off the GUI thread so the user can already be adjusting the
NEXT image while the previous one is still being written — this is what
makes the Space-Space-Space batch cadence possible.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from core.exporter import ExportResult, ExportSettings, export_crop
from models.crop_box import CropState

logger = logging.getLogger(__name__)


class _TaskSignals(QObject):
    finished = Signal(object)          # ExportResult


class _ExportTask(QRunnable):
    def __init__(self, source: Path, crop: CropState,
                 settings: ExportSettings) -> None:
        super().__init__()
        self._source = source
        self._crop = crop
        self._settings = settings
        self.signals = _TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = export_crop(self._source, self._crop, self._settings)
        except Exception as exc:       # belt & braces: never kill the pool
            logger.exception("Export task crashed for %s", self._source)
            result = ExportResult(source=self._source, error=str(exc))
        self.signals.finished.emit(result)


class ExportService(QObject):
    """Submit export jobs; results come back on the GUI thread."""

    export_finished = Signal(object)   # ExportResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)     # exports are heavier than thumbs
        self._in_flight: set[str] = set()

    def is_busy(self, source: Path) -> bool:
        return str(source) in self._in_flight

    def submit(self, source: Path, crop: CropState,
               settings: ExportSettings) -> bool:
        """Queue one export; refuses duplicates of an in-flight source."""
        key = str(source)
        if key in self._in_flight:
            logger.debug("Export already running for %s, ignored", source)
            return False
        self._in_flight.add(key)
        task = _ExportTask(source, crop, settings)
        task.signals.finished.connect(self._on_finished)
        self._pool.start(task)
        return True

    def _on_finished(self, result: ExportResult) -> None:
        self._in_flight.discard(str(result.source))
        self.export_finished.emit(result)
