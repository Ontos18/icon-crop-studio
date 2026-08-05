"""Configurable application shortcuts (Qt-free).

Action shortcuts live in :data:`DEFAULT_SHORTCUTS` as QKeySequence portable
strings (e.g. "Ctrl+O", "Left"). The user can override any of them through the
settings dialog; overrides are stored in ``AppConfig.shortcuts`` as a dict of
the same form, where an **empty string means the shortcut is disabled**.

This module is pure Python so the merge/conflict logic is unit-tested without
a QApplication. Interpreting the portable strings (``QKeySequence``) happens
only in the GUI layer (``ui/main_window.MainWindow._apply_shortcuts``).
"""
from __future__ import annotations

#: action id -> QKeySequence portable string.
DEFAULT_SHORTCUTS: dict[str, str] = {
    "open_dir": "Ctrl+O",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
    "prev_image": "Left",
    "next_image": "Right",
    "prev_page": "PageUp",
    "next_page": "PageDown",
    "export": "Ctrl+S",
    "export_next": "Space",
    "reset_crop": "Esc",
    "wrap_mode": "M",
    "settings": "Ctrl+,",
}


def merge_shortcuts(configured: dict[str, str] | None) -> dict[str, str]:
    """Effective shortcuts: defaults overridden by non-empty *configured*.

    A *configured* value of ``""`` is kept as-is (explicitly disables the
    shortcut); unknown action ids are ignored so an old config never breaks.
    """
    merged = dict(DEFAULT_SHORTCUTS)
    for action_id, sequence in (configured or {}).items():
        if action_id in merged:
            merged[action_id] = sequence
    return merged


def conflicts(shortcuts: dict[str, str]) -> dict[str, list[str]]:
    """Map each duplicated sequence to the action ids sharing it.

    Empty sequences (disabled shortcuts) are ignored. This feeds the settings
    dialog's conflict check and the merge logic's sanity tests.
    """
    by_sequence: dict[str, list[str]] = {}
    for action_id, sequence in shortcuts.items():
        if sequence.strip():
            by_sequence.setdefault(sequence.strip(), []).append(action_id)
    return {seq: ids for seq, ids in by_sequence.items() if len(ids) > 1}
