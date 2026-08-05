"""Unit tests for core.shortcuts (Qt-free)."""
from __future__ import annotations

from core.shortcuts import DEFAULT_SHORTCUTS, conflicts, merge_shortcuts


def test_defaults_have_no_conflicts() -> None:
    # 默认快捷键两两不冲突；全部非空
    assert not conflicts(DEFAULT_SHORTCUTS)
    assert all(v.strip() for v in DEFAULT_SHORTCUTS.values())


def test_merge_without_config_returns_defaults() -> None:
    assert merge_shortcuts(None) == DEFAULT_SHORTCUTS
    assert merge_shortcuts({}) == DEFAULT_SHORTCUTS


def test_merge_overrides_only_named_action() -> None:
    merged = merge_shortcuts({"export": "Ctrl+P"})
    assert merged["export"] == "Ctrl+P"
    assert merged["undo"] == DEFAULT_SHORTCUTS["undo"]


def test_merge_empty_string_disables() -> None:
    merged = merge_shortcuts({"undo": ""})
    assert merged["undo"] == ""


def test_merge_ignores_unknown_action_ids() -> None:
    merged = merge_shortcuts({"no_such_action": "Ctrl+X"})
    assert merged == DEFAULT_SHORTCUTS


def test_conflicts_groups_by_sequence() -> None:
    shortcuts = {"a": "Ctrl+1", "b": "Ctrl+1", "c": "Ctrl+2", "d": ""}
    assert conflicts(shortcuts) == {"Ctrl+1": ["a", "b"]}


def test_conflicts_ignores_disabled() -> None:
    assert conflicts({"a": "", "b": ""}) == {}


def test_merge_default_shortcuts_are_all_known() -> None:
    # 确保 DEFAULT_SHORTCUTS 与 UI 使用的 action id 集合一致
    expected = {"open_dir", "undo", "redo", "prev_image", "next_image",
                "prev_page", "next_page", "export", "export_next",
                "reset_crop", "wrap_mode", "settings"}
    assert set(DEFAULT_SHORTCUTS) == expected
