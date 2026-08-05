"""Settings dialog (Phase 10).

The dialog edits a *deep copy* of the config; Cancel therefore leaves the
real config untouched, and OK writes the copy back (via ``result_config``)
so MainWindow can save and apply the changes.

Shortcut editing uses a table of ``QKeySequenceEdit`` cells — one per
action. Clearing a cell (or pressing the editor's clear button) disables
that shortcut; on OK, duplicate sequences are rejected with a message so the
user resolves the conflict before closing.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from core.config_manager import AppConfig
from core.localization import AVAILABLE_LANGUAGES, tr
from core.shortcuts import DEFAULT_SHORTCUTS, conflicts, merge_shortcuts
from ui.theme import THEMES


class SettingsDialog(QDialog):
    """Edits a copy of the config; ``result_config`` holds the edited copy."""

    def __init__(self, config: AppConfig,
                 shortcut_labels: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = deepcopy(config)
        self._shortcut_labels = shortcut_labels

        # --- general settings --------------------------------------------
        self._language_combo = QComboBox(self)
        for code in AVAILABLE_LANGUAGES:
            self._language_combo.addItem(AVAILABLE_LANGUAGES[code], code)
        self._language_combo.setCurrentIndex(
            self._language_combo.findData(self._config.language))

        self._theme_combo = QComboBox(self)
        for theme in THEMES:
            self._theme_combo.addItem(tr(f"settings.theme.{theme}"), theme)
        self._theme_combo.setCurrentIndex(
            self._theme_combo.findData(self._config.theme or "system"))

        self._thumb_spin = QSpinBox(self)
        self._thumb_spin.setRange(32, 256)
        self._thumb_spin.setSingleStep(16)
        self._thumb_spin.setValue(self._config.thumbnail_size)

        self._move_speed_spin = QSpinBox(self)
        self._move_speed_spin.setRange(1, 50)
        self._move_speed_spin.setSingleStep(1)
        self._move_speed_spin.setValue(self._config.crop_move_speed)

        # --- 滚轮步长滑块（Shift+滚轮缩放裁切框 / Ctrl+滚轮缩放画布） ------
        self._wheel_resize_slider, self._wheel_resize_value, \
            self._wheel_resize_reset = self._build_slider_row(
                self._config.wheel_resize_step, 10, 300, 5, 100,
                lambda v: f"{v} px")
        self._wheel_zoom_slider, self._wheel_zoom_value, \
            self._wheel_zoom_reset = self._build_slider_row(
                round(self._config.wheel_zoom_step * 100),
                100, 200, 5, 125, lambda v: f"{v / 100:.2f}×")

        # --- 导出文件名模板 ----------------------------------------------
        self._template_edit = QLineEdit(self)
        self._template_edit.setText(self._config.filename_template)
        self._template_edit.setMaxLength(120)
        self._template_hint = QLabel(self)
        self._template_hint.setWordWrap(True)

        self._folder_watch = QCheckBox(self)
        self._folder_watch.setChecked(self._config.folder_watch_enabled)
        self._remember_crop = QCheckBox(self)
        self._remember_crop.setChecked(
            self._config.remember_crop_between_images)
        self._overwrite = QCheckBox(self)
        self._overwrite.setChecked(self._config.overwrite_existing)

        # --- shortcut table ------------------------------------------------
        self._table = QTableWidget(len(DEFAULT_SHORTCUTS), 2, self)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._editors: dict[str, QKeySequenceEdit] = {}
        merged = merge_shortcuts(self._config.shortcuts)
        for row, action_id in enumerate(sorted(DEFAULT_SHORTCUTS)):
            name_item = QTableWidgetItem(self._label_for(action_id))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)
            editor = QKeySequenceEdit(QKeySequence(merged[action_id]), self._table)
            editor.setClearButtonEnabled(True)   # 清空 = 禁用该快捷键
            self._table.setCellWidget(row, 1, editor)
            self._editors[action_id] = editor
        self._table.resizeRowsToContents()

        self._reset_shortcuts_button = QPushButton(self)
        self._reset_shortcuts_button.clicked.connect(self._reset_shortcuts)

        # --- buttons -------------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        # Labels live as widgets so retranslate_ui only swaps their text.
        self._language_label = QLabel(self)
        self._theme_label = QLabel(self)
        self._thumb_label = QLabel(self)
        self._move_speed_label = QLabel(self)
        self._wheel_resize_label = QLabel(self)
        self._wheel_zoom_label = QLabel(self)
        self._template_label = QLabel(self)

        self._build_layout()
        self.setMinimumWidth(460)
        self.retranslate_ui()

    # ------------------------------------------------------------------ API
    @property
    def result_config(self) -> AppConfig:
        """The edited copy; call :meth:`apply` first to flush controls in."""
        return self._config

    def apply(self) -> None:
        """Flush current control values into the edited config copy."""
        self._config.language = self._language_combo.currentData()
        self._config.theme = self._theme_combo.currentData()
        self._config.thumbnail_size = self._thumb_spin.value()
        self._config.crop_move_speed = self._move_speed_spin.value()
        self._config.wheel_resize_step = self._wheel_resize_slider.value()
        self._config.wheel_zoom_step = self._wheel_zoom_slider.value() / 100.0
        self._config.filename_template = self._template_edit.text().strip()
        self._config.folder_watch_enabled = self._folder_watch.isChecked()
        self._config.remember_crop_between_images = self._remember_crop.isChecked()
        self._config.overwrite_existing = self._overwrite.isChecked()
        self._config.shortcuts = self._overridden_shortcuts()

    # -------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        self._general_group = QGroupBox(self)
        form = QFormLayout(self._general_group)
        form.addRow(self._language_label, self._language_combo)
        form.addRow(self._theme_label, self._theme_combo)
        form.addRow(self._thumb_label, self._thumb_spin)
        form.addRow(self._move_speed_label, self._move_speed_spin)
        form.addRow(self._wheel_resize_label, self._slider_widget(
            self._wheel_resize_slider, self._wheel_resize_value,
            self._wheel_resize_reset))
        form.addRow(self._wheel_zoom_label, self._slider_widget(
            self._wheel_zoom_slider, self._wheel_zoom_value,
            self._wheel_zoom_reset))
        form.addRow(self._template_label, self._template_edit)
        form.addRow(self._template_hint)
        form.addRow(self._folder_watch)
        form.addRow(self._remember_crop)
        form.addRow(self._overwrite)

        self._shortcuts_group = QGroupBox(self)
        shortcuts_layout = QVBoxLayout(self._shortcuts_group)
        shortcuts_layout.addWidget(self._table)
        shortcuts_layout.addWidget(self._reset_shortcuts_button)

        root = QVBoxLayout(self)
        root.addWidget(self._general_group)
        root.addWidget(self._shortcuts_group, 1)
        root.addWidget(self._button_box)

    # --------------------------------------------------------------- i18n
    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("settings.title"))
        self._general_group.setTitle(tr("settings.general"))
        self._shortcuts_group.setTitle(tr("settings.shortcuts"))
        self._language_label.setText(tr("settings.language"))
        self._theme_label.setText(tr("settings.theme"))
        self._thumb_label.setText(tr("settings.thumbnail_size"))
        self._move_speed_label.setText(tr("settings.crop_move_speed"))
        self._wheel_resize_label.setText(tr("settings.wheel_resize_step"))
        self._wheel_zoom_label.setText(tr("settings.wheel_zoom_step"))
        self._wheel_resize_reset.setText(tr("settings.reset_default"))
        self._wheel_zoom_reset.setText(tr("settings.reset_default"))
        self._template_label.setText(tr("settings.filename_template"))
        self._template_hint.setText(tr("settings.filename_template_hint"))
        self._folder_watch.setText(tr("settings.folder_watch"))
        self._remember_crop.setText(tr("settings.remember_crop"))
        self._overwrite.setText(tr("settings.overwrite"))
        self._table.setHorizontalHeaderLabels(
            [tr("settings.shortcuts.action"), tr("settings.shortcuts.sequence")])
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("settings.ok"))
        self._button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("settings.cancel"))
        self._reset_shortcuts_button.setText(
            tr("settings.shortcuts.reset"))

    # ------------------------------------------------------------- internal
    def _build_slider_row(
        self, value: int, lo: int, hi: int, step: int, default: int,
        fmt: Callable[[int], str],
    ) -> tuple[QSlider, QLabel, QPushButton]:
        """一行"滑块 + 当前值 + 恢复默认"控件，返回三件套。"""
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(lo, hi)
        slider.setSingleStep(step)
        slider.setValue(value)
        value_label = QLabel(fmt(value), self)
        reset_btn = QPushButton(self)
        slider.valueChanged.connect(lambda v: value_label.setText(fmt(v)))
        reset_btn.clicked.connect(lambda: slider.setValue(default))
        return slider, value_label, reset_btn

    def _slider_widget(self, slider: QSlider, value_label: QLabel,
                       reset_btn: QPushButton) -> QWidget:
        """把滑块 + 数值 + 恢复默认按钮装进一行，作为表单字段。"""
        widget = QWidget(self)
        lay = QHBoxLayout(widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(slider, 1)
        lay.addWidget(value_label)
        lay.addWidget(reset_btn)
        return widget

    def _label_for(self, action_id: str) -> str:
        return self._shortcut_labels.get(action_id, action_id)

    def _collect_shortcuts(self) -> dict[str, str]:
        return {
            aid: editor.keySequence().toString(
                QKeySequence.SequenceFormat.PortableText)
            for aid, editor in self._editors.items()
        }

    def _overridden_shortcuts(self) -> dict[str, str]:
        """Keep only entries differing from the defaults (empty = disabled)."""
        return {aid: seq for aid, seq in self._collect_shortcuts().items()
                if seq != DEFAULT_SHORTCUTS.get(aid)}

    def _reset_shortcuts(self) -> None:
        for action_id, editor in self._editors.items():
            editor.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[action_id]))

    def accept(self) -> None:
        clashes = conflicts(self._collect_shortcuts())
        if clashes:
            seq = next(iter(clashes))
            names = " / ".join(self._label_for(aid) for aid in clashes[seq])
            QMessageBox.warning(
                self, tr("settings.shortcuts"),
                tr("settings.shortcuts.conflict", seq=seq, actions=names))
            return
        super().accept()
