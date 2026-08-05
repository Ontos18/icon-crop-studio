"""Right pane: output folder, formats, sizes, auto-next, export button.

The panel owns the export *preferences* (persisted straight into the
config) and can assemble an ``ExportSettings`` snapshot on demand.
The actual export flow (what to export, when, status updates) stays in
MainWindow.

Sizes (Phase 13)
----------------
* One unified list of size entries: preset squares (16…256) plus any
  user-defined sizes (e.g. 800×800 or 100×200). Every entry can be removed
  with its ✕ button, and new ones added via the input row.
* Only sizes sharing the *same* aspect ratio can be selected at once —
  picking a size from another ratio clears the previous selection, keeping
  the crop box a single consistent rectangle shape.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from core.config_manager import DEFAULT_SIZE_ENTRIES, ConfigManager
from core.exporter import EXPORT_FORMATS, ExportSettings
from core.localization import tr
from models.crop_box import reduce_aspect
from models.image_item import ImageStatus
from ui.widgets.crop_preview import CropPreview
from ui.widgets.path_picker import PathPicker

#: Upper bound for user-defined sizes (keeps the crop box sane).
_MAX_CUSTOM = 4096

#: ICO 预设尺寸（删除时弹确认，避免误删后难以找回）。
_PRESET_SIZES: frozenset[tuple[int, int]] = frozenset(
    tuple(s) for s in DEFAULT_SIZE_ENTRIES)

#: 状态图例色，与 thumbnail_panel._STATUS_COLORS 保持一致。
_LEGEND_ORDER = (
    ImageStatus.UNPROCESSED, ImageStatus.PROCESSING,
    ImageStatus.EXPORTED, ImageStatus.FAILED,
)
_LEGEND_COLORS: dict[ImageStatus, str] = {
    ImageStatus.UNPROCESSED: "#9e9e9e",   # gray
    ImageStatus.PROCESSING: "#1976d2",    # blue
    ImageStatus.EXPORTED: "#2e7d32",      # green
    ImageStatus.FAILED: "#c62828",        # red
}

_SIZE_RE = re.compile(r"^\s*(\d+)\s*[*xX×]\s*(\d+)\s*$")


def parse_custom_size(text: str) -> tuple[int, int] | None:
    """Parse "800*800" / "100x200" / "300×400" into (w, h), or None."""
    m = _SIZE_RE.match(text)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w < 1 or h < 1 or w > _MAX_CUSTOM or h > _MAX_CUSTOM:
        return None
    return w, h


def size_label(size: tuple[int, int]) -> str:
    """'16' for a square, '100×200' otherwise (display text)."""
    w, h = size
    return f"{w}" if w == h else f"{w}×{h}"


class ExportPanel(QWidget):
    """Export settings + export trigger button."""

    output_dir_changed = Signal(str)
    export_requested = Signal()
    settings_changed = Signal()      # a format/size/auto-next toggle changed
    aspect_changed = Signal(int, int)   # 激活输出尺寸的比例 (aw, ah)
    wrap_mode_changed = Signal(bool)    # 裁切模式单选变化（普通/越界）
    aspect_switched = Signal(int, int)  # 用户切换到不同比例组 (aw, ah)

    def __init__(self, config_manager: ConfigManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        config = config_manager.config

        self.output_picker = PathPicker(
            "panel.export.output_dir", "dialog.open_dir.title", self)
        self.output_picker.set_path(config.output_dir)
        self.output_picker.path_changed.connect(self.output_dir_changed)

        # --- formats ------------------------------------------------------
        self._format_group = QGroupBox(self)
        self._format_checks: dict[str, QCheckBox] = {}
        format_layout = QGridLayout(self._format_group)
        for column, fmt in enumerate(EXPORT_FORMATS):
            check = QCheckBox(fmt.upper(), self._format_group)
            check.setChecked(fmt in config.export_formats)
            check.toggled.connect(self._persist)
            format_layout.addWidget(check, 0, column)
            self._format_checks[fmt] = check

        # --- sizes ----------------------------------------------------------
        self._size_group = QGroupBox(self)
        #: 所有尺寸条目（含预设方形与自定义），统一增删。
        self._all_sizes: list[tuple[int, int]] = [
            (w, h) for w, h in config.size_entries]
        #: 勾选的尺寸（同比例，由互斥逻辑保证）。
        self._selected: set[tuple[int, int]] = {
            (w, h) for w, h in config.selected_sizes}
        initial = self.selected_sizes()
        self._active_aspect = reduce_aspect(*initial[0]) if initial else None
        self._size_checks: dict[tuple[int, int], QCheckBox] = {}
        self._build_size_ui()

        # --- 裁切模式：普通 / 包裹 --------------------------------------------
        self._wrap_normal = QRadioButton(self)
        self._wrap_wrap = QRadioButton(self)
        self._wrap_normal.setChecked(not config.wrap_mode)
        self._wrap_wrap.setChecked(config.wrap_mode)
        # 单选组互斥：只监听“包裹”这一枚即可拿到两种状态的切换。
        self._wrap_wrap.toggled.connect(self._on_wrap_toggled)
        wrap_row = QHBoxLayout()
        wrap_row.setSpacing(8)
        wrap_row.addWidget(self._wrap_normal)
        wrap_row.addWidget(self._wrap_wrap)
        wrap_row.addStretch(1)

        # --- behaviour + button ---------------------------------------------
        self._auto_next_check = QCheckBox(self)
        self._auto_next_check.setChecked(config.auto_next_after_export)
        self._auto_next_check.toggled.connect(self._persist)

        self._export_button = QPushButton(self)
        self._export_button.setDefault(False)
        self._export_button.setAutoDefault(False)
        # Space must stay free as the global "export & next" shortcut, so
        # the button must never steal it as focus-activation.
        self._export_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._export_button.clicked.connect(self.export_requested)

        # 左侧缩略图状态角标的图例（灰/蓝/绿/红）。
        self._legend_label = QLabel(self)
        self._legend_label.setTextFormat(Qt.TextFormat.RichText)
        self._legend_label.setStyleSheet("color: palette(mid);")

        self._preview = CropPreview(self)   # Phase 7 live preview

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.output_picker)
        layout.addWidget(self._format_group)
        layout.addWidget(self._size_group)
        layout.addLayout(wrap_row)
        layout.addWidget(self._auto_next_check)
        layout.addWidget(self._export_button)
        layout.addWidget(self._legend_label)
        layout.addWidget(self._preview, 1)

        self.retranslate_ui()
        # 保证初始选中集合比例一致，并同步裁切框比例。
        self._apply_active_aspect()

    # ------------------------------------------------------------------ API
    def current_settings(self) -> ExportSettings:
        """Snapshot of the panel state, ready for the exporter."""
        config = self._config_manager.config
        return ExportSettings(
            formats=tuple(f for f, c in self._format_checks.items()
                          if c.isChecked()),
            sizes=tuple(self.selected_sizes()),
            output_dir=Path(self.output_picker.path),
            overwrite=config.overwrite_existing,
            template=config.filename_template,
            wrap=self._wrap_wrap.isChecked(),
        )

    @property
    def auto_next(self) -> bool:
        return self._auto_next_check.isChecked()

    @property
    def active_aspect(self) -> tuple[int, int] | None:
        """当前激活的输出尺寸比例组，无选中时返回 None。"""
        return self._active_aspect

    def selected_sizes(self) -> list[tuple[int, int]]:
        """Currently checked sizes, in the entry list's order."""
        return [s for s in self._all_sizes if s in self._selected]

    def _legend_text(self) -> str:
        """状态角标图例 HTML（颜色与缩略图角标保持一致）。"""
        names = {
            ImageStatus.UNPROCESSED: tr("status.name.unprocessed"),
            ImageStatus.PROCESSING: tr("status.name.processing"),
            ImageStatus.EXPORTED: tr("status.name.exported"),
            ImageStatus.FAILED: tr("status.name.failed"),
        }
        return "  ".join(
            f"<span style='color:{_LEGEND_COLORS[s]}'>●</span> {names[s]}"
            for s in _LEGEND_ORDER)

    def set_preview(self, image) -> None:
        """Feed the live preview; pass a null QImage to clear it."""
        self._preview.set_preview(image, self.selected_sizes())

    def set_wrap_mode(self, wrap: bool) -> None:
        """同步模式单选（由工具栏 action 驱动），不重复广播。"""
        target = bool(wrap)
        if self._wrap_wrap.isChecked() == target:
            return
        self._wrap_wrap.blockSignals(True)
        self._wrap_wrap.setChecked(target)
        self._wrap_normal.setChecked(not target)
        self._wrap_wrap.blockSignals(False)

    def _on_wrap_toggled(self, _checked: bool) -> None:
        """模式单选变化：广播新模式（持久化由 MainWindow 统一入口负责）。"""
        self.wrap_mode_changed.emit(self._wrap_wrap.isChecked())
        self.settings_changed.emit()

    def set_export_enabled(self, enabled: bool) -> None:
        self._export_button.setEnabled(enabled)

    def retranslate_ui(self) -> None:
        self.output_picker.retranslate_ui()
        self._format_group.setTitle(tr("panel.export.formats"))
        self._size_group.setTitle(tr("panel.export.sizes"))
        self._auto_next_check.setText(tr("panel.export.auto_next"))
        self._wrap_normal.setText(tr("panel.export.mode_normal"))
        self._wrap_wrap.setText(tr("panel.export.mode_wrap"))
        self._wrap_normal.setToolTip(tr("panel.export.mode_normal_hint"))
        self._wrap_wrap.setToolTip(tr("action.wrap_mode_hint"))
        self._export_button.setText(tr("panel.export.button"))
        self._legend_label.setText(self._legend_text())
        self._add_edit.setPlaceholderText(tr("panel.export.custom_hint"))
        self._add_button.setText(tr("panel.export.custom_add"))
        self._preview.update()          # CropPreview 自绘占位文案

    # ------------------------------------------------------- size panel
    def _build_size_ui(self) -> None:
        """一次构建固定的尺寸区结构；增删时只重填 ``_entries``。"""
        root = QVBoxLayout(self._size_group)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(2)
        self._entries = QVBoxLayout()
        self._entries.setSpacing(0)
        root.addLayout(self._entries)
        self._add_edit = QLineEdit(self._size_group)
        self._add_edit.setMaxLength(20)
        self._add_edit.returnPressed.connect(self._add_size)
        self._add_button = QPushButton(self._size_group)
        self._add_button.clicked.connect(self._add_size)
        add_row = QHBoxLayout()
        add_row.setSpacing(2)
        add_row.addWidget(self._add_edit, 1)
        add_row.addWidget(self._add_button)
        root.addLayout(add_row)
        self._rebuild_entries()

    def _rebuild_entries(self) -> None:
        """重填尺寸条目行（同步清空，避免控件叠加）。"""
        self._clear_layout(self._entries)
        self._size_checks.clear()
        for size in self._all_sizes:
            row = QHBoxLayout()
            row.setSpacing(2)
            check = QCheckBox(self._size_group)
            check.blockSignals(True)
            check.setChecked(size in self._selected)
            check.blockSignals(False)
            check.toggled.connect(
                lambda _checked=False, s=size: self._on_size_toggled(s))
            self._size_checks[size] = check
            label = QLabel(size_label(size), self._size_group)
            label.setToolTip(f"{size[0]} × {size[1]} px")
            del_btn = QPushButton("✕", self._size_group)
            del_btn.setFixedWidth(22)
            del_btn.setToolTip(tr("panel.export.custom_delete"))
            del_btn.clicked.connect(
                lambda _checked=False, s=size: self._remove_size(s))
            row.addWidget(check)
            row.addWidget(label, 1)
            row.addWidget(del_btn)
            self._entries.addLayout(row)

    @staticmethod
    def _clear_layout(layout) -> None:
        """同步移除 layout 下的所有子项（widget 立即 detach，再排程删除）。"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                ExportPanel._clear_layout(item.layout())

    def _on_size_toggled(self, size: tuple[int, int]) -> None:
        """勾选某尺寸：其比例成为唯一激活组，其他比例组的勾选被清除。

        若用户切换到不同的比例组，发射 ``aspect_switched`` 供状态栏提示，
        避免"勾选被静默清空"造成困惑。
        """
        checked = self._size_checks[size].isChecked()
        self._selected.discard(size)
        if checked:
            new_aspect = reduce_aspect(*size)
            old_aspect = self._active_aspect
            self._active_aspect = new_aspect
            self._selected.add(size)
            if old_aspect is not None and old_aspect != new_aspect:
                self.aspect_switched.emit(*new_aspect)
        self._apply_active_aspect()

    def _apply_active_aspect(self) -> None:
        """只保留比例与激活组相同的勾选，并同步控件 / 配置 / 裁切框比例。"""
        aspect = self._active_aspect
        if aspect is None:
            self._selected.clear()
        else:
            self._selected = {
                s for s in self._selected if reduce_aspect(*s) == aspect}
        if not self._selected:
            self._active_aspect = None
        self._sync_checks()
        self._persist()
        self.settings_changed.emit()
        aw, ah = self._active_aspect or (1, 1)
        self.aspect_changed.emit(aw, ah)

    def _sync_checks(self) -> None:
        for size, check in self._size_checks.items():
            target = size in self._selected
            if check.isChecked() != target:
                check.blockSignals(True)
                check.setChecked(target)
                check.blockSignals(False)

    # -------------------------------------------------- add / remove
    def _add_size(self) -> None:
        size = parse_custom_size(self._add_edit.text())
        if size is None:
            QMessageBox.warning(
                self, tr("panel.export.custom"),
                tr("msg.custom_invalid"))
            return
        if size in self._all_sizes:
            QMessageBox.information(
                self, tr("panel.export.custom"),
                tr("msg.custom_duplicate", size=size_label(size)))
            return
        self._all_sizes.append(size)
        self._add_edit.clear()
        self._rebuild_entries()
        self._apply_active_aspect()
        self.settings_changed.emit()

    def _remove_size(self, size: tuple[int, int]) -> None:
        if size not in self._all_sizes:
            return
        # 预设尺寸删除前确认，避免误删 ICO 常用尺寸后难以找回。
        if size in _PRESET_SIZES:
            answer = QMessageBox.question(
                self, tr("panel.export.sizes"),
                tr("msg.delete_preset_size", size=size_label(size)))
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._all_sizes.remove(size)
        self._selected.discard(size)
        self._rebuild_entries()
        self._apply_active_aspect()
        self.settings_changed.emit()

    # ------------------------------------------------------------- internal
    def _persist(self) -> None:
        """Mirror every change straight into the config file."""
        config = self._config_manager.config
        config.export_formats = [f for f, c in self._format_checks.items()
                                 if c.isChecked()]
        config.size_entries = [list(s) for s in self._all_sizes]
        config.selected_sizes = [
            list(s) for s in self._all_sizes if s in self._selected]
        config.auto_next_after_export = self._auto_next_check.isChecked()
        self._config_manager.save()
