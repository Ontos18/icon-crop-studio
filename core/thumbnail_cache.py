"""Asynchronous thumbnail generation with an LRU cache.

Thumbnails are decoded in QThreadPool worker threads (QImageReader with
``setScaledSize`` decodes JPEG/PNG at reduced size — much cheaper than
loading full resolution), then delivered to the GUI thread through a
queued signal. The GUI never blocks on image decoding.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

logger = logging.getLogger(__name__)

_CACHE_CAPACITY = 512   # ~512 * 96*96*4 bytes ≈ 18 MB worst case


class _TaskSignals(QObject):
    """QRunnable cannot own signals; this tiny QObject carries them."""

    finished = Signal(str, QImage)   # path (str), scaled image (may be null)


class _ThumbnailTask(QRunnable):
    """Decode one image at thumbnail size in a worker thread."""

    def __init__(self, path: Path, size: int) -> None:
        super().__init__()
        self._path = path
        self._size = size
        self.signals = _TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        image = QImage()
        try:
            reader = QImageReader(str(self._path))
            reader.setAutoTransform(True)          # honor EXIF rotation
            source = reader.size()                 # header only, no decode
            if source.isValid() and not source.isEmpty():
                scaled = source.scaled(
                    QSize(self._size, self._size),
                    Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled)
            image = reader.read()                  # first frame for GIF
            if image.isNull():
                logger.warning("Thumbnail decode failed for %s: %s",
                               self._path, reader.errorString())
        except Exception:                           # never kill the pool
            logger.exception("Thumbnail task crashed for %s", self._path)
        self.signals.finished.emit(str(self._path), image)


class ThumbnailCache(QObject):
    """Request-and-forget thumbnail provider.

    Usage:  connect to :attr:`thumbnail_ready`, call :meth:`request`.
    Duplicate requests for a path already cached or in flight are ignored.
    """

    thumbnail_ready = Signal(str, QImage)

    def __init__(self, thumbnail_size: int = 96,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._size = thumbnail_size
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._pending: set[str] = set()
        self._pool = QThreadPool(self)
        # Decoding is I/O + CPU mixed; a few threads keep pages snappy
        # without starving the GUI process.
        self._pool.setMaxThreadCount(max(2, QThreadPool.globalInstance()
                                         .maxThreadCount() // 2))

    # ------------------------------------------------------------------ API
    @property
    def thumbnail_size(self) -> int:
        return self._size

    def set_thumbnail_size(self, size: int) -> None:
        """Changing the size invalidates everything (settings dialog)."""
        if size != self._size:
            self._size = size
            self.clear()

    def get(self, path: Path) -> QImage | None:
        """Cached thumbnail or None (marks entry as recently used)."""
        key = str(path)
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
        return image

    def request(self, path: Path) -> None:
        """Ensure a thumbnail for ``path`` will be emitted (async)."""
        key = str(path)
        if key in self._cache:
            self.thumbnail_ready.emit(key, self._cache[key])
            return
        if key in self._pending:
            return
        self._pending.add(key)
        task = _ThumbnailTask(path, self._size)
        task.signals.finished.connect(self._on_task_finished)
        self._pool.start(task)

    def clear(self) -> None:
        self._cache.clear()
        self._pool.clear()          # drop queued (not yet started) tasks
        self._pending.clear()

    # ------------------------------------------------------------- internal
    def _on_task_finished(self, key: str, image: QImage) -> None:
        self._pending.discard(key)
        if not image.isNull():
            self._cache[key] = image
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_CAPACITY:
                self._cache.popitem(last=False)
        self.thumbnail_ready.emit(key, image)
