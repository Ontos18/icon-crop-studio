"""Application theme switching (system / light / dark).

Implementation notes
--------------------
* Every theme uses the ``Fusion`` style. Fusion paints purely from the
  QPalette and never reads the OS color scheme — the previous ``windows11``
  native style drew menus / toolbars / buttons / dialogs with the OS dark
  theme regardless of the palette, which made "light" show white text on
  dark-native controls when Windows itself was in dark mode. Fusion is the
  only reliable way to guarantee light mode = black text on every system.
* After a style/palette change every top-level widget is unpolished/polished
  so existing widgets repaint with the new colors (this is what re-colors
  QGraphicsView canvases etc. without rebuilding the UI).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES: tuple[str, ...] = ("system", "light", "dark")

#: Fusion 自绘风格与平台无关，彻底规避系统深色对浅色主题的污染。
_FUSION_STYLE = "Fusion"


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` to ``app``.

    ``system`` follows the OS color scheme; ``light`` / ``dark`` are explicit.
    Light mode is always Fusion + a hand-built light palette, so the text
    color is black under any OS setting.
    """
    if theme == "dark" or (theme == "system" and _is_dark_system()):
        app.setStyle(_FUSION_STYLE)
        app.setPalette(_dark_palette())
    else:
        app.setStyle(_FUSION_STYLE)
        app.setPalette(_light_palette())
    _repolish(app)


def _is_dark_system() -> bool:
    """Whether the OS is currently in dark mode (system theme only)."""
    app = QApplication.instance()
    if app is None:
        return False
    hints = app.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:      # older Qt without colorScheme()
        return False


def _repolish(app: QApplication) -> None:
    for widget in app.topLevelWidgets():
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()


def _light_palette() -> QPalette:
    """Explicit light palette (white background, dark text).

    Hand-constructed so light mode is dark-on-light regardless of the OS color
    scheme — the old ``standardPalette()`` leaked OS-dark colors onto the
    "light" theme on some Qt builds.
    """
    palette = QPalette()
    window = QColor("#f0f0f0")
    base = QColor("#ffffff")
    text = QColor("#1a1a1a")
    disabled = QColor("#a0a0a0")
    highlight = QColor("#2a82da")

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, window)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#c62828"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffdc"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9e9e9e"))
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#4c4cff"))

    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.Highlight, QColor("#c8c8c8"))
    return palette


def _dark_palette() -> QPalette:
    palette = QPalette()
    window = QColor("#353535")
    base = QColor("#2b2b2b")
    text = QColor("#e8e8e8")
    disabled = QColor("#7a7a7a")
    highlight = QColor("#2a82da")

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#404040"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, window)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff5252"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, base)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9e9e9e"))
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#4cc2ff"))

    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.Highlight, QColor("#4a4a4a"))
    return palette
