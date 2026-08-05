"""Async crop previews (Qt bridge, mirrors ``core.export_service``).

The GUI thread asks for a preview of ``(path, crop)``; decoding + cropping
runs on a small thread pool so dragging the crop box never blocks the UI.
Results arrive back on the GUI thread through :attr:`PreviewService.preview_ready`.

A monotonically increasing *generation* counter lets the GUI invalidate
stale results after switching images; the service drops any result that
belongs to an older generation before emitting.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from core.exporter import crop_to_preview
from models.crop_box import CropState

logger = logging.getLogger(__name__)

#: (path, x, y, w, h, brightness, wrap) — uniquely identifies one crop+look.
PreviewKey = tuple[str, int, int, int, int, int, bool]


class _PreviewSignals(QObject):
    """QRunnable cannot own signals; this tiny QObject carries them."""

    finished = Signal(object, int, QImage)   # key, generation, image


class _PreviewTask(QRunnable):
    """Decode + crop one preview in a worker thread."""

    def __init__(self, path: Path, crop: CropState, max_size: int,
                 generation: int, brightness: int = 0,
                 wrap: bool = False) -> None:
        super().__init__()
        self._path = path
        self._crop = crop
        self._max_size = max_size
        self._generation = generation
        self._brightness = brightness
        self._wrap = wrap
        self._key: PreviewKey = (
            str(path), crop.x, crop.y, crop.w, crop.h, brightness, wrap)
        self.signals = _PreviewSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        image = QImage()
        try:
            image = _pil_to_qimage(crop_to_preview(
                self._path, self._crop, self._max_size, self._brightness,
                self._wrap))
        except Exception:                        # never kill the pool
            logger.exception("Preview failed for %s", self._path)
        self.signals.finished.emit(self._key, self._generation, image)


def _pil_to_qimage(image: Image.Image) -> QImage:
    """RGBA PIL image -> QImage (copies the buffer; safe across threads)."""
    width, height = image.size
    data = image.tobytes("raw", "RGBA")
    return QImage(data, width, height, width * 4,
                  QImage.Format.Format_RGBA8888).copy()


class PreviewService(QObject):
    """Request crop previews; results come back on the GUI thread.

    A duplicate request for the same ``(path, crop)`` that is still in flight
    is ignored. Call :meth:`bump_generation` when the current image changes so
    results for the previous image are discarded on arrival.
    """

    preview_ready = Signal(str, QImage)   # path, preview (may be null)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)          # one decode at a time is plenty
        self._in_flight: set[PreviewKey] = set()
        self._generation = 0

    # ------------------------------------------------------------------ API
    def generation(self) -> int:
        return self._generation

    def bump_generation(self) -> None:
        """Invalidate all in-flight results (the current image changed)."""
        self._generation += 1

    def request(self, path: Path, crop: CropState, max_size: int = 256,
                brightness: int = 0, wrap: bool = False) -> bool:
        """Queue one preview; refuses duplicates of an in-flight crop."""
        key: PreviewKey = (str(path), crop.x, crop.y, crop.w, crop.h,
                           brightness, wrap)
        if key in self._in_flight:
            return False
        self._in_flight.add(key)
        task = _PreviewTask(path, crop, max_size, self._generation,
                            brightness, wrap)
        task.signals.finished.connect(self._on_finished)
        self._pool.start(task)
        return True

    def clear(self) -> None:
        self._pool.clear()          # drop queued (not yet started) tasks
        self._in_flight.clear()

    # ------------------------------------------------------------- internal
    def _on_finished(self, key: PreviewKey, generation: int, image: QImage) -> None:
        self._in_flight.discard(key)
        if generation != self._generation:
            logger.debug("Dropping stale preview for %s", key[0])
            return
        self.preview_ready.emit(key[0], image)
