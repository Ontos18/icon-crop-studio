"""Watching the input directory for added/removed images (Qt bridge).

``QFileSystemWatcher`` only reports *that* a watched directory changed, not
*which* file, so we keep a snapshot of the supported images and diff after a
short debounce. A slow poll timer acts as a fallback for network drives and
NTFS quirks where the watcher may miss events; ``diff_paths`` is a pure
function so the whole logic is unit-testable without Qt.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from core.image_loader import scan_directory

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 150
_POLL_MS = 2000


def diff_paths(snapshot: set[Path], current: set[Path]) -> tuple[list[Path], list[Path]]:
    """(newly-added, newly-removed) paths, each sorted Explorer-style."""
    added = sorted(current - snapshot, key=lambda p: p.name.lower())
    removed = sorted(snapshot - current, key=lambda p: p.name.lower())
    return added, removed


class FolderWatcher(QObject):
    """Watch one directory; emit :attr:`files_added` / :attr:`files_removed`."""

    files_added = Signal(list)      # list[Path]
    files_removed = Signal(list)    # list[Path]

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._dir: Path | None = None
        self._snapshot: set[Path] = set()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._scan)

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._scan)

        self._watcher.directoryChanged.connect(self._on_directory_changed)

    # ------------------------------------------------------------------ API
    def set_directory(self, directory: Path | None) -> None:
        """Watch ``directory``, or stop watching when None. Idempotent."""
        if self._dir == directory:
            return
        self._stop()
        self._dir = directory
        if directory is not None:
            self._poll.start()
            self._scan()            # initial snapshot without emitting
            logger.info("FolderWatcher watching %s", directory)

    def stop(self) -> None:
        self._stop()

    # ------------------------------------------------------------- internal
    def _on_directory_changed(self, _path: str) -> None:
        self._debounce.start()

    def _stop(self) -> None:
        for path in self._watcher.directories():
            self._watcher.removePath(path)
        self._poll.stop()
        self._debounce.stop()
        self._snapshot = set()
        self._dir = None

    def _scan(self) -> None:
        directory = self._dir
        if directory is None:
            return
        if not directory.is_dir():
            # The folder itself disappeared: drop the snapshot but keep the
            # poll running so a recreated folder is picked up automatically.
            self._snapshot = set()
            if str(directory) in self._watcher.directories():
                self._watcher.removePath(str(directory))
            return
        if str(directory) not in self._watcher.directories():
            self._watcher.addPath(str(directory))   # recreated after deletion
            self._debounce.start()
            return
        current = set(scan_directory(directory))
        added, removed = diff_paths(self._snapshot, current)
        self._snapshot = current
        if added:
            self.files_added.emit(added)
        if removed:
            self.files_removed.emit(removed)
