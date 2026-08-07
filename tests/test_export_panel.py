"""Unit tests for the pure helpers in ui.widgets.export_panel.

These functions (custom-size parsing, size labels) are Qt-free; importing
the module does not require a running QApplication.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from ui.theme import apply_theme
from ui.widgets.export_panel import ExportPanel, parse_custom_size, size_label


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


def test_status_legend_text_follows_light_and_dark_theme(tmp_path: Path) -> None:
    """Rich-text status names must stay readable after a theme switch."""
    app = QApplication.instance() or QApplication([])
    manager = ConfigManager(tmp_path / "config.json")
    manager.load()

    panel = ExportPanel(manager)
    apply_theme(app, "light")
    panel.retranslate_ui()
    assert "color:#1a1a1a" in panel._legend_label.text()

    apply_theme(app, "dark")
    panel.retranslate_ui()
    assert "color:#e8e8e8" in panel._legend_label.text()
