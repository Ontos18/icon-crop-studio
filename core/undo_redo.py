"""Generic bounded undo/redo stack over immutable state snapshots (Qt-free).

Snapshot-based rather than command-based on purpose: crop states are tiny
(three ints), so storing full snapshots is simpler and impossible to get
wrong compared with inverse-command bookkeeping.
"""
from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class UndoStack(Generic[T]):
    """History of states; ``current`` is always a valid state after reset."""

    def __init__(self, limit: int = 200) -> None:
        if limit < 2:
            raise ValueError("limit must be >= 2")
        self._limit = limit
        self._states: list[T] = []
        self._index: int = -1

    # ------------------------------------------------------------ properties
    @property
    def current(self) -> T | None:
        if 0 <= self._index < len(self._states):
            return self._states[self._index]
        return None

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    # ------------------------------------------------------------------ API
    def reset(self, initial: T) -> None:
        """Start a fresh history (e.g. a new image was opened)."""
        self._states = [initial]
        self._index = 0

    def push(self, state: T) -> None:
        """Append ``state``, dropping any redo branch. No-op if unchanged."""
        if self.current == state:
            return
        del self._states[self._index + 1:]
        self._states.append(state)
        if len(self._states) > self._limit:
            del self._states[0]
        self._index = len(self._states) - 1

    def undo(self) -> T | None:
        if not self.can_undo:
            return None
        self._index -= 1
        return self._states[self._index]

    def redo(self) -> T | None:
        if not self.can_redo:
            return None
        self._index += 1
        return self._states[self._index]
