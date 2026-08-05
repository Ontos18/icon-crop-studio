"""Unit tests for core.undo_redo (no Qt required)."""
from __future__ import annotations

import pytest

from core.undo_redo import UndoStack


def test_fresh_stack_has_no_history() -> None:
    stack: UndoStack[int] = UndoStack()
    assert stack.current is None
    assert not stack.can_undo and not stack.can_redo
    assert stack.undo() is None and stack.redo() is None


def test_reset_seeds_initial_state() -> None:
    stack: UndoStack[int] = UndoStack()
    stack.reset(1)
    assert stack.current == 1
    assert not stack.can_undo


def test_push_undo_redo_cycle() -> None:
    stack: UndoStack[int] = UndoStack()
    stack.reset(1)
    stack.push(2)
    stack.push(3)
    assert stack.undo() == 2
    assert stack.undo() == 1
    assert stack.undo() is None
    assert stack.redo() == 2
    assert stack.redo() == 3
    assert stack.redo() is None


def test_push_after_undo_drops_redo_branch() -> None:
    stack: UndoStack[int] = UndoStack()
    stack.reset(1)
    stack.push(2)
    stack.push(3)
    stack.undo()                 # back at 2
    stack.push(9)
    assert not stack.can_redo
    assert stack.undo() == 2


def test_duplicate_push_is_noop() -> None:
    stack: UndoStack[int] = UndoStack()
    stack.reset(1)
    stack.push(1)
    assert not stack.can_undo


def test_limit_drops_oldest() -> None:
    stack: UndoStack[int] = UndoStack(limit=3)
    stack.reset(0)
    for i in range(1, 6):
        stack.push(i)
    assert stack.current == 5
    stack.undo()
    stack.undo()
    assert stack.current == 3    # 0, 1, 2 dropped
    assert not stack.can_undo


def test_invalid_limit_rejected() -> None:
    with pytest.raises(ValueError):
        UndoStack(limit=1)
