"""Unit tests for core.folder_watcher.

Only the pure ``diff_paths`` function is tested here — instantiating
``FolderWatcher`` would require a QApplication + real filesystem events.
"""
from __future__ import annotations

from pathlib import Path

from core.folder_watcher import diff_paths


def test_diff_both_empty() -> None:
    assert diff_paths(set(), set()) == ([], [])


def test_diff_added_only() -> None:
    a, b = Path("a.png"), Path("b.png")
    added, removed = diff_paths(set(), {a, b})
    assert added == [a, b]
    assert removed == []


def test_diff_removed_only() -> None:
    a, b = Path("a.png"), Path("b.png")
    added, removed = diff_paths({a, b}, set())
    assert added == []
    assert removed == [a, b]


def test_diff_mixed_sorted_case_insensitive() -> None:
    a, b, c = Path("A.png"), Path("b.png"), Path("c.png")
    added, removed = diff_paths({b}, {a, c})
    assert added == [a, c]          # "a.png" 排在最前
    assert removed == [b]


def test_diff_unchanged_is_empty() -> None:
    a = Path("a.png")
    assert diff_paths({a}, {a}) == ([], [])
