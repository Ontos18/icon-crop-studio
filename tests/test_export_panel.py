"""Unit tests for the pure helpers in ui.widgets.export_panel.

These functions (custom-size parsing, size labels) are Qt-free; importing
the module does not require a running QApplication.
"""
from __future__ import annotations

from ui.widgets.export_panel import parse_custom_size, size_label


def test_parse_valid_variants() -> None:
    assert parse_custom_size("800*800") == (800, 800)
    assert parse_custom_size("100x200") == (100, 200)
    assert parse_custom_size("300×400") == (300, 400)
    assert parse_custom_size(" 50 * 60 ") == (50, 60)
    assert parse_custom_size("1x1") == (1, 1)


def test_parse_invalid_inputs() -> None:
    for bad in ("", "abc", "100", "100x", "x200", "0x100", "100x0",
                "-5x10", "100x200x300", "1.5x2", "10 20"):
        assert parse_custom_size(bad) is None, f"应拒绝: {bad!r}"


def test_parse_rejects_oversize() -> None:
    assert parse_custom_size("9999x10") is None
    assert parse_custom_size("10x9999") is None


def test_size_label() -> None:
    assert size_label((16, 16)) == "16"
    assert size_label((800, 800)) == "800"
    assert size_label((100, 200)) == "100×200"
