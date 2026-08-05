"""A one-line "label: <clickable path>" row used for input/output folders.

Clicking the path (or the tool button) opens a folder dialog; the chosen
path is emitted via :attr:`path_changed`. The path text is middle-elided
so long paths never break the layout; the full path lives in the tooltip.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from core.localization import tr


class _ElidedLinkLabel(QLabel):
    """Label that middle-elides its text and reacts to clicks."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Native-looking "link" color from the palette, no web styling.
        self.setStyleSheet("color: palette(link); text-decoration: underline;")
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           self.sizePolicy().verticalPolicy())

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._update_elide()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802 (Qt API)
        super().resizeEvent(event)
        self._update_elide()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _update_elide(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, self.width()))


class PathPicker(QWidget):
    """``标题:  C:\\...\\folder  [浏览…]`` — click either to change."""

    path_changed = Signal(str)   # new absolute path

    def __init__(self, title_key: str, dialog_title_key: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title_key = title_key
        self._dialog_title_key = dialog_title_key
        self._path = ""

        self._title_label = QLabel(self)
        self._path_label = _ElidedLinkLabel(self)
        # 点击蓝色路径 = 在资源管理器中打开当前目录；浏览按钮负责选择新目录。
        self._path_label.clicked.connect(self._open_in_explorer)
        self._browse_button = QPushButton(self)
        self._browse_button.setFlat(False)
        self._browse_button.clicked.connect(self.browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self._title_label)
        layout.addWidget(self._path_label, 1)
        layout.addWidget(self._browse_button)

        self.retranslate_ui()

    # ------------------------------------------------------------------ API
    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        """Set programmatically (no signal — signals are for user actions)."""
        self._path = path
        self._refresh_path_label()

    def browse(self) -> None:
        start = self._path if self._path else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, tr(self._dialog_title_key), start)
        if chosen and chosen != self._path:
            self._path = chosen
            self._refresh_path_label()
            self.path_changed.emit(chosen)

    def retranslate_ui(self) -> None:
        self._title_label.setText(tr(self._title_key))
        self._browse_button.setText(tr("panel.export.browse"))
        self._refresh_path_label()

    # ------------------------------------------------------------- internal
    def _open_in_explorer(self) -> None:
        """在系统文件管理器中打开当前目录（路径未设置/无效时忽略）。"""
        if not self._path:
            return
        path = Path(self._path)
        if not path.is_dir():
            return
        if sys.platform == "win32":
            os.startfile(str(path))            # noqa: S606  # Windows Explorer
        else:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path)))

    def _refresh_path_label(self) -> None:
        self._path_label.set_full_text(
            self._path if self._path else tr("path.not_set"))
