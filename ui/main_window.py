"""Main application window.

Phase 3: the three placeholder panes are now real widgets —
thumbnail panel (paged, async thumbnails), interim image preview,
export panel skeleton. MainWindow is the single owner of application
state (the ImageCollection); panels only render it and report user
intent back via signals.
"""
from __future__ import annotations

import base64
import dataclasses
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDropEvent, QImage,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QHeaderView, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSlider, QSplitter, QStyle, QTableWidget, QTableWidgetItem,
    QToolBar, QVBoxLayout,
)

from app_info import APP_VERSION
from core.config_manager import ConfigManager
from core.export_service import ExportService
from core.exporter import ExportResult, validate_settings
from core.folder_watcher import FolderWatcher
from core.image_loader import filter_supported, scan_directory
from core.localization import AVAILABLE_LANGUAGES, localization, tr
from core.preview_service import PreviewService
from core.shortcuts import DEFAULT_SHORTCUTS, merge_shortcuts
from core.thumbnail_cache import ThumbnailCache
from models.crop_box import CropState
from models.image_collection import ImageCollection
from models.image_item import ImageStatus
from ui.theme import apply_theme
from ui.widgets.crop_editor import CropEditor
from ui.widgets.export_panel import ExportPanel
from ui.widgets.settings_dialog import SettingsDialog
from ui.widgets.thumbnail_panel import ThumbnailPanel

logger = logging.getLogger(__name__)

# Left / center / right proportions required by the spec.
_PANE_STRETCH: tuple[int, int, int] = (20, 60, 20)

#: Pretty display for shortcut hints appended to toolbar button text.
_KEY_DISPLAY: dict[str, str] = {
    "Left": "←", "Right": "→", "Up": "↑", "Down": "↓",
}

#: action id -> i18n key, for the settings dialog's shortcut rows.
_SHORTCUT_LABEL_KEYS: dict[str, str] = {
    "open_dir": "action.open_dir",
    "undo": "menu.edit.undo",
    "redo": "menu.edit.redo",
    "prev_image": "action.prev_image",
    "next_image": "action.next_image",
    "prev_page": "panel.thumbnails.prev_page",
    "next_page": "panel.thumbnails.next_page",
    "export": "action.export",
    "export_next": "action.export_next",
    "reset_crop": "action.reset_crop",
    "wrap_mode": "action.wrap_mode",
    "settings": "menu.tools.settings",
}

#: toolbar action -> standard icon (Phase 11: no shipped asset files).
_TOOLBAR_ICONS: dict[str, QStyle.StandardPixmap] = {
    "action_open_dir": QStyle.StandardPixmap.SP_DirOpenIcon,
    "action_prev_image": QStyle.StandardPixmap.SP_ArrowBack,
    "action_next_image": QStyle.StandardPixmap.SP_ArrowForward,
    "action_export": QStyle.StandardPixmap.SP_DialogSaveButton,
    "action_export_next": QStyle.StandardPixmap.SP_MediaSeekForward,
    "action_wrap_mode": QStyle.StandardPixmap.SP_FileDialogContentsView,
}


def _shortcut_hint(action: QAction) -> str:
    """Human-readable shortcut of ``action`` ('' if none)."""
    sequence = action.shortcut()
    if sequence.isEmpty():
        return ""
    text = sequence.toString(QKeySequence.SequenceFormat.NativeText)
    return _KEY_DISPLAY.get(text, text)


def _parse_relative(text: str) -> tuple[float, float, float] | None:
    """Parse "cx,cy,nw" (each 0~1); None for empty/invalid input.

    Also accepts the legacy 4-value form "nx,ny,nw,nh" and converts it to
    the center representation, so old configs keep working.
    """
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(",")]
        # 包裹模式下裁切框可越界，归一化位置允许落在 [0,1] 之外；只要求
        # 宽度占比为正。普通模式的记录仍在此范围内，兼容旧配置。
        if len(parts) == 3 and parts[2] > 0:
            return parts[0], parts[1], parts[2]
        if len(parts) == 4 and parts[2] > 0:
            nx, ny, nw, nh = parts
            return nx + nw / 2, ny + nh / 2, nw
    except (ValueError, AttributeError):
        pass
    return None


def _format_relative(value: tuple[float, float, float] | None) -> str:
    """Serialize the normalized crop to "cx,cy,nw" ('' when None)."""
    if value is None:
        return ""
    return ",".join(f"{v:.4f}" for v in value)


class MainWindow(QMainWindow):
    """Application shell + owner of the image collection state."""

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self._config_manager = config_manager
        config = config_manager.config

        self._collection = ImageCollection(page_size=config.thumbnail_page_size)
        self._thumbnail_cache = ThumbnailCache(config.thumbnail_size, self)
        #: 上次编辑的裁切框归一化位置 (cx, cy, nw)：中心点相对位置 + 宽度占比。
        #: 跨图片按比例继承（尺寸不同也适用），并在关闭软件时持久化到配置。
        self._last_crop_relative: tuple[float, float, float] | None = (
            _parse_relative(config.last_crop_relative))
        #: path currently shown in the editor (for folder-watch bookkeeping).
        self._displayed_path: Path | None = None
        #: 图片异步加载期间用户按过导出 → 记录 auto_next，加载完成后补执行。
        self._pending_export_next: bool | None = None
        self._export_service = ExportService(self)
        self._export_service.export_finished.connect(self._on_export_finished)

        # Phase 7 live preview: debounced so dragging the crop box doesn't
        # fire one decode per mouse move.
        self._preview_service = PreviewService(self)
        self._preview_service.preview_ready.connect(self._on_preview_ready)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._refresh_preview)

        # Phase 9 folder watch: adds/removes appear in the thumbnail list live.
        self._folder_watcher = FolderWatcher(self)
        self._folder_watcher.files_added.connect(self._on_watch_files_added)
        self._folder_watcher.files_removed.connect(self._on_watch_files_removed)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_central_layout()
        self._create_statusbar()
        self.setAcceptDrops(True)

        # 恢复上次的包裹模式（无图时仅记录状态，图片加载后生效）。
        self.panel_editor.set_wrap_mode(config.wrap_mode)
        self.panel_export.set_wrap_mode(config.wrap_mode)

        localization.subscribe(self.retranslate_ui)
        self.retranslate_ui()

        self.resize(1280, 800)
        self._restore_geometry()

        # Reopen last folder so a returning user is immediately productive.
        if config.input_dir and Path(config.input_dir).is_dir():
            self._load_directory(Path(config.input_dir))

    # ------------------------------------------------------------- actions
    def _create_actions(self) -> None:
        """All QActions live here; shortcuts come from the Phase 5 config."""
        self.action_open_dir = QAction(self)
        self.action_open_dir.triggered.connect(self._choose_input_dir)

        self.action_exit = QAction(self)
        self.action_exit.setShortcut(QKeySequence("Alt+F4"))  # not rebindable
        self.action_exit.triggered.connect(self.close)

        self.action_undo = QAction(self)
        self.action_undo.setEnabled(False)

        self.action_redo = QAction(self)
        self.action_redo.setEnabled(False)

        self.action_prev_image = QAction(self)
        self.action_prev_image.triggered.connect(self._select_prev_image)

        self.action_next_image = QAction(self)
        self.action_next_image.triggered.connect(self._select_next_image)

        self.action_prev_page = QAction(self)
        self.action_prev_page.triggered.connect(self._go_prev_page)

        self.action_next_page = QAction(self)
        self.action_next_page.triggered.connect(self._go_next_page)

        self.action_export = QAction(self)
        self.action_export.setEnabled(False)
        self.action_export.triggered.connect(
            lambda: self._export_current(auto_next=False))

        self.action_export_next = QAction(self)
        self.action_export_next.setEnabled(False)
        self.action_export_next.triggered.connect(
            lambda: self._export_current(auto_next=True))

        self.action_reset_crop = QAction(self)
        self.action_reset_crop.setEnabled(False)
        self.action_reset_crop.triggered.connect(self._reset_crop)

        self.action_wrap_mode = QAction(self)
        self.action_wrap_mode.setCheckable(True)
        self.action_wrap_mode.setChecked(self._config_manager.config.wrap_mode)
        self.action_wrap_mode.triggered.connect(self._toggle_wrap)

        self.action_settings = QAction(self)
        self.action_settings.triggered.connect(self._show_settings)

        self.action_about = QAction(self)
        self.action_about.triggered.connect(self._show_about)

        self.action_shortcuts_help = QAction(self)
        self.action_shortcuts_help.triggered.connect(self._show_shortcuts_help)

        # Phase 5 configurable shortcuts: action id -> QAction.
        self._shortcut_actions: dict[str, QAction] = {
            "open_dir": self.action_open_dir,
            "undo": self.action_undo,
            "redo": self.action_redo,
            "prev_image": self.action_prev_image,
            "next_image": self.action_next_image,
            "prev_page": self.action_prev_page,
            "next_page": self.action_next_page,
            "export": self.action_export,
            "export_next": self.action_export_next,
            "reset_crop": self.action_reset_crop,
            "wrap_mode": self.action_wrap_mode,
            "settings": self.action_settings,
        }
        self._apply_shortcuts()

        # Language switching: one checkable action per available language.
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self._language_actions: dict[str, QAction] = {}
        for code, native_name in AVAILABLE_LANGUAGES.items():
            act = QAction(native_name, self)
            act.setCheckable(True)
            act.setChecked(code == localization.language)
            act.triggered.connect(
                lambda _checked=False, c=code: self._switch_language(c))
            self._language_group.addAction(act)
            self._language_actions[code] = act

    # ------------------------------------------------------------ shortcuts
    def _apply_shortcuts(self) -> None:
        """Push the merged default/config shortcuts onto every QAction."""
        merged = merge_shortcuts(self._config_manager.config.shortcuts)
        for action_id, action in self._shortcut_actions.items():
            action.setShortcut(QKeySequence(merged.get(action_id, "")))

    def _reset_crop(self) -> None:
        if hasattr(self, "panel_editor"):
            self.panel_editor.reset_crop()

    def _on_brightness_changed(self, value: int) -> None:
        """亮度滑块 -> 显示亮度 + 实时预览（导出也应用该亮度）。"""
        if hasattr(self, "panel_editor"):
            self.panel_editor.set_brightness(value)
            self._schedule_preview()

    def _reset_brightness(self) -> None:
        """还原到原图亮度（滑块回中间）。"""
        self._brightness_slider.setValue(0)

    # --------------------------------------------------------------- menus
    def _create_menus(self) -> None:
        bar = self.menuBar()
        self._menu_file = bar.addMenu("")
        self._menu_file.addAction(self.action_open_dir)
        self._menu_file.addSeparator()
        self._menu_file.addAction(self.action_export)
        self._menu_file.addAction(self.action_export_next)
        self._menu_file.addSeparator()
        self._menu_file.addAction(self.action_exit)

        self._menu_edit = bar.addMenu("")
        self._menu_edit.addAction(self.action_undo)
        self._menu_edit.addAction(self.action_redo)
        self._menu_edit.addSeparator()
        self._menu_edit.addAction(self.action_reset_crop)

        self._menu_view = bar.addMenu("")
        self._menu_view.addAction(self.action_prev_image)
        self._menu_view.addAction(self.action_next_image)
        self._menu_view.addAction(self.action_prev_page)
        self._menu_view.addAction(self.action_next_page)
        self._menu_view.addSeparator()
        self._menu_view.addAction(self.action_wrap_mode)
        self._menu_view.addSeparator()
        self._menu_language = self._menu_view.addMenu("")
        for act in self._language_actions.values():
            self._menu_language.addAction(act)

        self._menu_tools = bar.addMenu("")
        self._menu_tools.addAction(self.action_settings)

        self._menu_help = bar.addMenu("")
        self._menu_help.addAction(self.action_shortcuts_help)
        self._menu_help.addAction(self.action_about)

    # ------------------------------------------------------------- toolbar
    def _create_toolbar(self) -> None:
        self._toolbar = QToolBar(self)
        self._toolbar.setObjectName("main_toolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # Phase 11: standard theme icons — no shipped asset files needed.
        for attr, pixmap in _TOOLBAR_ICONS.items():
            getattr(self, attr).setIcon(self.style().standardIcon(pixmap))
        self._toolbar.addAction(self.action_open_dir)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self.action_prev_image)
        self._toolbar.addAction(self.action_next_image)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self.action_export)
        self._toolbar.addAction(self.action_export_next)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self.action_wrap_mode)

        # --- 亮度调整（显示层，不修改原图）--------------------------------
        self._toolbar.addSeparator()
        self._brightness_label = QLabel(self)
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._brightness_slider.setRange(-100, 100)
        self._brightness_slider.setValue(0)
        self._brightness_slider.setFixedWidth(160)
        self._brightness_slider.setSingleStep(5)
        self._brightness_slider.setPageStep(10)
        self._brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self._brightness_reset = QPushButton(self)
        self._brightness_reset.setFlat(True)
        self._brightness_reset.clicked.connect(self._reset_brightness)
        self._toolbar.addWidget(self._brightness_label)
        self._toolbar.addWidget(self._brightness_slider)
        self._toolbar.addWidget(self._brightness_reset)
        self.addToolBar(self._toolbar)

    # -------------------------------------------------------------- layout
    def _create_central_layout(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setChildrenCollapsible(False)

        self.panel_thumbnails = ThumbnailPanel(
            self._collection, self._thumbnail_cache, self._splitter)
        self.panel_thumbnails.image_activated.connect(self._on_image_activated)
        self.panel_thumbnails.input_dir_changed.connect(
            lambda p: self._load_directory(Path(p)))
        self.panel_thumbnails.input_picker.set_path(
            self._config_manager.config.input_dir)

        self.panel_editor = CropEditor(
            self._splitter,
            move_speed=self._config_manager.config.crop_move_speed,
            wheel_resize_step=self._config_manager.config.wheel_resize_step,
            wheel_zoom_step=self._config_manager.config.wheel_zoom_step)
        self.panel_editor.crop_changed.connect(self._on_crop_changed)
        self.panel_editor.crop_changed.connect(self._schedule_preview)
        self.panel_editor.image_loaded.connect(self._on_image_loaded)
        self.panel_editor.undo_available.connect(self.action_undo.setEnabled)
        self.panel_editor.redo_available.connect(self.action_redo.setEnabled)
        self.action_undo.triggered.connect(self.panel_editor.undo)
        self.action_redo.triggered.connect(self.panel_editor.redo)

        self.panel_export = ExportPanel(self._config_manager, self._splitter)
        self.panel_export.output_dir_changed.connect(self._on_output_dir_changed)
        self.panel_export.export_requested.connect(
            lambda: self._export_current(auto_next=self.panel_export.auto_next))
        self.panel_export.settings_changed.connect(self._schedule_preview)
        # 输出尺寸比例变化 -> 裁切框即时切换为对应比例。
        self.panel_export.aspect_changed.connect(
            lambda w, h: self.panel_editor.set_aspect(w, h))
        # 导出面板的模式单选 -> 主窗口统一入口（与工具栏/快捷键同步）。
        self.panel_export.wrap_mode_changed.connect(self._on_panel_wrap_changed)
        # 切换尺寸比例组 -> 状态栏提示（静默清空不再无解释）。
        self.panel_export.aspect_switched.connect(self._on_aspect_switched)
        self.panel_export.set_export_enabled(False)

        # ExportPanel 构造时会先发射一次 aspect_changed（此时尚未连接），
        # 因此这里手动同步初始比例给裁切框。
        aspect = self.panel_export.active_aspect
        if aspect is not None:
            self.panel_editor.set_aspect(*aspect)

        for index, stretch in enumerate(_PANE_STRETCH):
            self._splitter.setStretchFactor(index, stretch)
        self._splitter.setSizes([s * 12 for s in _PANE_STRETCH])

        self.setCentralWidget(self._splitter)

    # ----------------------------------------------------------- statusbar
    def _create_statusbar(self) -> None:
        self._status_message = QLabel(self)
        self.statusBar().addWidget(self._status_message, 1)

    # ---------------------------------------------------------------- i18n
    def retranslate_ui(self) -> None:
        """Re-apply every visible string; called on each language switch."""
        self.setWindowTitle(tr("app.title"))

        self._menu_file.setTitle(tr("menu.file"))
        self._menu_edit.setTitle(tr("menu.edit"))
        self._menu_view.setTitle(tr("menu.view"))
        self._menu_language.setTitle(tr("menu.view.language"))
        self._menu_tools.setTitle(tr("menu.tools"))
        self._menu_help.setTitle(tr("menu.help"))

        self.action_open_dir.setText(tr("menu.file.open_dir"))
        self.action_exit.setText(tr("menu.file.exit"))
        self.action_undo.setText(tr("menu.edit.undo"))
        self.action_redo.setText(tr("menu.edit.redo"))
        self.action_prev_image.setText(tr("action.prev_image"))
        self.action_next_image.setText(tr("action.next_image"))
        self.action_prev_page.setText(tr("panel.thumbnails.prev_page"))
        self.action_next_page.setText(tr("panel.thumbnails.next_page"))
        self.action_export.setText(tr("action.export"))
        self.action_export_next.setText(tr("action.export_next"))
        self.action_reset_crop.setText(tr("action.reset_crop"))
        self.action_wrap_mode.setText(tr("action.wrap_mode"))
        self.action_wrap_mode.setToolTip(tr("action.wrap_mode_hint"))
        self.action_settings.setText(tr("menu.tools.settings"))
        self.action_about.setText(tr("menu.help.about"))
        self.action_shortcuts_help.setText(tr("menu.help.shortcuts"))
        self._toolbar.setWindowTitle(tr("toolbar.main"))
        self._brightness_label.setText(tr("toolbar.brightness"))
        self._brightness_slider.setToolTip(tr("toolbar.brightness_hint"))
        self._brightness_reset.setText(tr("toolbar.brightness_reset"))

        # Toolbar buttons show their shortcut, e.g. "上一张 (←)".
        # setIconText affects toolbar buttons only, so menu entries keep the
        # plain text (menus already render shortcuts in their own column).
        for action, key in (
            (self.action_open_dir, "action.open_dir"),
            (self.action_prev_image, "action.prev_image"),
            (self.action_next_image, "action.next_image"),
            (self.action_export, "action.export"),
            (self.action_export_next, "action.export_next"),
            (self.action_wrap_mode, "action.wrap_mode"),
        ):
            hint = _shortcut_hint(action)
            base = tr(key)
            action.setIconText(f"{base} ({hint})" if hint else base)

        # Ctrl+S 被禁用（空快捷键）时提示，避免用户误以为保存功能坏了。
        merged = merge_shortcuts(self._config_manager.config.shortcuts)
        if merged.get("export"):
            self.action_export.setToolTip(tr("action.export"))
        else:
            self.action_export.setToolTip(tr("toolbar.export_disabled_hint"))

        self.panel_thumbnails.retranslate_ui()
        self.panel_editor.retranslate_ui()
        self.panel_export.retranslate_ui()
        self._update_status()

    def _switch_language(self, code: str) -> None:
        if localization.set_language(code):
            self._config_manager.config.language = code
            self._config_manager.save()

    # ---------------------------------------------------------------- wrap
    def _toggle_wrap(self, checked: bool) -> None:
        """工具栏按钮 / 快捷键触发的模式切换入口。"""
        self._apply_wrap_mode(bool(checked))

    def _on_panel_wrap_changed(self, wrap: bool) -> None:
        """导出面板单选变化；与工具栏/快捷键共享同一应用入口。"""
        self._apply_wrap_mode(wrap)

    def _on_aspect_switched(self, aw: int, ah: int) -> None:
        """用户切换尺寸比例组时给出状态栏反馈（提示清空了其他比例）。"""
        self.statusBar().showMessage(
            tr("msg.aspect_switched", ratio=f"{aw}:{ah}"), 3000)

    def _apply_wrap_mode(self, wrap: bool) -> None:
        """包裹模式统一入口：写配置 + 同步三个控件 + 刷新预览。"""
        config = self._config_manager.config
        if config.wrap_mode == wrap:
            return
        config.wrap_mode = wrap
        self._config_manager.save()
        self.action_wrap_mode.blockSignals(True)
        self.action_wrap_mode.setChecked(wrap)
        self.action_wrap_mode.blockSignals(False)
        self.panel_editor.set_wrap_mode(wrap)
        self.panel_export.set_wrap_mode(wrap)
        self._schedule_preview()
        self.statusBar().showMessage(
            tr("status.wrap_on" if wrap else "status.wrap_off"), 3000)

    # -------------------------------------------------------------- settings
    def _show_settings(self) -> None:
        """Open the settings dialog; apply on OK (Cancel leaves everything)."""
        labels = {aid: tr(_SHORTCUT_LABEL_KEYS.get(aid, aid))
                  for aid in DEFAULT_SHORTCUTS}
        dialog = SettingsDialog(self._config_manager.config, labels, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self._config_manager.replace(dialog.result_config)
            self._config_manager.save()
            self._apply_settings()

    def _apply_settings(self) -> None:
        """Propagate the (already saved) config to every live subsystem."""
        config = self._config_manager.config
        localization.set_language(config.language)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, config.theme)
        self.panel_thumbnails.set_thumbnail_size(config.thumbnail_size)
        self.panel_editor.set_move_speed(config.crop_move_speed)
        self.panel_editor.set_wheel_resize_step(config.wheel_resize_step)
        self.panel_editor.set_wheel_zoom_step(config.wheel_zoom_step)
        self._apply_shortcuts()
        self._restart_folder_watch()
        self.retranslate_ui()

    def _restart_folder_watch(self) -> None:
        if (self._config_manager.config.folder_watch_enabled
                and self._config_manager.config.input_dir):
            self._folder_watcher.set_directory(
                Path(self._config_manager.config.input_dir))
        else:
            self._folder_watcher.stop()

    # ------------------------------------------------------- image loading
    def _choose_input_dir(self) -> None:
        self.panel_thumbnails.input_picker.browse()   # emits input_dir_changed

    def _load_directory(self, directory: Path) -> None:
        # Stop watching the old folder first so its change events can't be
        # attributed to the new one while we scan it.
        self._folder_watcher.stop()
        images = scan_directory(directory)
        self._collection.load(images)
        self._config_manager.config.input_dir = str(directory)
        self._config_manager.save()
        self.panel_thumbnails.input_picker.set_path(str(directory))
        self.panel_thumbnails.refresh()
        self.panel_editor.clear()
        self._displayed_path = None
        self.panel_export.set_preview(QImage())
        self._update_navigation_actions()
        self._update_status()
        # Auto-select the first image: the user can start cropping
        # immediately without one extra click.
        if images:
            self._select_image(0)
        self._restart_folder_watch()

    def _on_output_dir_changed(self, path: str) -> None:
        self._config_manager.config.output_dir = path
        self._config_manager.save()

    # ----------------------------------------------------------- selection
    def _on_image_activated(self, global_index: int) -> None:
        self._select_image(global_index)

    def _select_image(self, global_index: int) -> None:
        page_before = self._collection.current_page
        if not self._collection.select(global_index):
            return
        if self._collection.current_page != page_before:
            self.panel_thumbnails.refresh()
        else:
            self.panel_thumbnails.sync_selection()
        item = self._collection.current_item
        if item is not None:
            self._displayed_path = item.path
            # 异步解码：切图不阻塞 UI，位置记忆与预览在 image_loaded 后处理。
            self.panel_editor.set_image(item.path)
            self.panel_editor.setFocus()   # WASD/QE work immediately
            self._preview_service.bump_generation()
        else:
            self._displayed_path = None
            self.panel_export.set_preview(QImage())
        self._update_navigation_actions()
        self._update_status()

    def _on_image_loaded(self, path: Path) -> None:
        """图片解码完成并显示：应用位置记忆、刷新预览与状态栏。"""
        if self._displayed_path != path:
            return      # 用户已切换到其他图片
        if (self._config_manager.config.remember_crop_between_images
                and self._last_crop_relative is not None):
            self._apply_relative_crop()
        self._preview_service.bump_generation()
        self._schedule_preview()
        # 关键：图片异步加载完成前 has_image() 为 False，导出按钮/快捷键
        # 处于禁用状态；这里必须重新启用，否则"第一张图按 Enter 没反应"。
        self._update_navigation_actions()
        self._update_status()
        # 图片加载期间用户按过导出 → 自动补执行（保持批量 Enter 工作流顺畅）。
        if self._pending_export_next is not None:
            auto = self._pending_export_next
            self._pending_export_next = None
            self._export_current(auto_next=auto)

    def _select_prev_image(self) -> None:
        if self._collection.current_index > 0:
            self._select_image(self._collection.current_index - 1)

    def _select_next_image(self) -> None:
        self._select_image(self._collection.current_index + 1)

    def _go_prev_page(self) -> None:
        if self._collection.prev_page():
            self.panel_thumbnails.refresh()

    def _go_next_page(self) -> None:
        if self._collection.next_page():
            self.panel_thumbnails.refresh()

    def _update_navigation_actions(self) -> None:
        count = len(self._collection)
        index = self._collection.current_index
        self.action_prev_image.setEnabled(index > 0)
        self.action_next_image.setEnabled(index < count - 1)
        has_image = self.panel_editor.has_image()
        self.action_export.setEnabled(has_image)
        self.action_export_next.setEnabled(has_image)
        self.action_reset_crop.setEnabled(has_image)
        self.panel_export.set_export_enabled(has_image)

    # -------------------------------------------------------------- export
    def _export_current(self, *, auto_next: bool) -> None:
        item = self._collection.current_item
        crop = self.panel_editor.current_state()
        if item is None:
            return
        if crop is None:
            # 图片还在异步解码：记录意图，加载完成后自动补一次导出，
            # 而不是静默放弃（否则批量按 Enter 会"没反应"）。
            self._pending_export_next = auto_next
            self.statusBar().showMessage(tr("status.image_loading"), 4000)
            return
        settings = dataclasses.replace(
            self.panel_export.current_settings(),
            brightness=self.panel_editor.brightness())
        problem = validate_settings(settings)
        if problem is not None:
            self.statusBar().showMessage(tr(problem), 4000)
            if problem == "msg.no_output_dir":
                self.panel_export.output_picker.browse()
            return
        if not self._export_service.submit(item.path, crop, settings):
            return                      # same image already exporting
        item.status = ImageStatus.PROCESSING
        self.panel_thumbnails.update_status_badge(item.path)
        logger.info("Export queued: %s", item.path.name)
        # Move on immediately — the export finishes in the background,
        # which is what makes the Space-Space-Space cadence possible.
        if auto_next and self._collection.current_index < len(self._collection) - 1:
            self._select_next_image()

    def _on_export_finished(self, result: ExportResult) -> None:
        index = self._collection.index_of(result.source)   # O(1) path lookup
        if index >= 0:
            item = self._collection.items[index]
            item.status = (ImageStatus.EXPORTED if result.ok
                           else ImageStatus.FAILED)
            self.panel_thumbnails.update_status_badge(item.path)
        if result.ok:
            self.statusBar().showMessage(
                tr("status.exported", name=result.source.name,
                   count=len(result.outputs)), 3000)
        else:
            error = tr(result.error) if result.error.startswith("msg.") \
                else result.error
            self.statusBar().showMessage(
                tr("status.export_failed", name=result.source.name,
                   error=error), 6000)

    def _on_crop_changed(self, state: CropState) -> None:
        size = self.panel_editor.image_size()
        if size is not None and size[0] > 0 and size[1] > 0:
            # 记录归一化的中心点与宽度占比，保证不同尺寸图片之间可移植。
            img_w, img_h = size
            self._last_crop_relative = (
                (state.x + state.w / 2) / img_w,
                (state.y + state.h / 2) / img_h,
                state.w / img_w)
        self._update_status()

    def _apply_relative_crop(self) -> None:
        """把归一化位置映射到当前图片并应用（尺寸/位置越界由模型 clamp）。

        以宽度占比推导缩放因子 k，高度按当前裁切框比例自动推导。
        """
        size = self.panel_editor.image_size()
        if size is None or self._last_crop_relative is None:
            return
        img_w, img_h = size
        cx, cy, nw = self._last_crop_relative
        aw, ah = self.panel_editor.aspect
        k = max(1, round(nw * img_w / aw))
        w, h = k * aw, k * ah
        # (cx, cy) 是中心点，换算成左上角；越界由模型 clamp。
        x = round(cx * img_w - w / 2)
        y = round(cy * img_h - h / 2)
        self.panel_editor.apply_initial_state(CropState(x, y, w, h))

    def _update_status(self) -> None:
        item = self._collection.current_item
        if item is not None:
            parts = [item.name]
            crop = self.panel_editor.current_state()
            if crop is not None:
                parts.append(tr("status.crop",
                                size=f"{crop.w}×{crop.h}",
                                x=crop.x, y=crop.y))
            parts.append(tr("status.images_loaded",
                            count=len(self._collection)))
            self._status_message.setText("  —  ".join(parts))
        elif len(self._collection):
            self._status_message.setText(
                tr("status.images_loaded", count=len(self._collection)))
        else:
            self._status_message.setText(tr("status.ready"))

    # -------------------------------------------------------------- preview
    def _schedule_preview(self, *_args: object) -> None:
        """Debounce preview refresh (crop drags fire many signals)."""
        self._preview_timer.start()

    def _refresh_preview(self) -> None:
        item = self._collection.current_item
        crop = self.panel_editor.current_state()
        if item is None or crop is None or not self.panel_export.selected_sizes():
            self.panel_export.set_preview(QImage())
            return
        # Bump the generation so only the newest request's result is shown
        # (dragging the box or flipping sizes invalidates older previews).
        self._preview_service.bump_generation()
        self._preview_service.request(
            item.path, crop, brightness=self.panel_editor.brightness(),
            wrap=self._config_manager.config.wrap_mode)

    def _on_preview_ready(self, path: str, image: QImage) -> None:
        item = self._collection.current_item
        if item is None or str(item.path) != path:
            return        # user moved on; drop the stale preview
        self.panel_export.set_preview(image)

    # ---------------------------------------------------------- folder watch
    def _on_watch_files_added(self, paths: list[Path]) -> None:
        added = self._collection.append(paths)
        if added:
            self.panel_thumbnails.refresh()
            self._update_navigation_actions()
            self._update_status()
            logger.info("Folder watch: %d image(s) added", added)

    def _on_watch_files_removed(self, paths: list[Path]) -> None:
        removed = self._collection.remove(paths)
        if not removed:
            return
        removed_set = set(paths)
        if (self._displayed_path is not None
                and self._displayed_path in removed_set):
            item = self._collection.current_item
            if item is None:
                self.panel_editor.clear()
                self._displayed_path = None
                self.panel_export.set_preview(QImage())
            else:
                self._select_image(self._collection.current_index)
        else:
            self.panel_thumbnails.refresh()
        self._update_navigation_actions()
        self._update_status()
        logger.info("Folder watch: %d image(s) removed", removed)

    # ----------------------------------------------------------- drag&drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt API)
        paths = [Path(url.toLocalFile())
                 for url in event.mimeData().urls() if url.isLocalFile()]
        directories = [p for p in paths if p.is_dir()]
        files = filter_supported([p for p in paths if p.is_file()])

        if directories and not files and len(self._collection) == 0:
            # Dropping a single folder onto an empty session = open it.
            self._load_directory(directories[0])
            return

        added = 0
        for directory in directories:
            added += self._collection.append(scan_directory(directory))
        if files:
            added += self._collection.append(files)
        if added:
            self.panel_thumbnails.refresh()
            self._update_navigation_actions()
            self._update_status()
            logger.info("Drag&drop added %d images", added)

    # ------------------------------------------------------------- dialogs
    def _show_about(self) -> None:
        QMessageBox.about(self, tr("about.title"),
                          tr("about.text", version=APP_VERSION))

    def _show_shortcuts_help(self) -> None:
        """弹出"快捷键一览"对话框，内容由配置动态生成。

        直接复用快捷键注册表，无需维护第二份清单；被禁用的快捷键显示"已禁用"。
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("help.shortcuts.title"))
        table = QTableWidget(len(DEFAULT_SHORTCUTS), 2, dialog)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        merged = merge_shortcuts(self._config_manager.config.shortcuts)
        for row, action_id in enumerate(sorted(DEFAULT_SHORTCUTS)):
            name_item = QTableWidgetItem(
                tr(_SHORTCUT_LABEL_KEYS.get(action_id, action_id)))
            seq = merged[action_id]
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, QTableWidgetItem(
                seq if seq else tr("help.shortcuts.disabled")))
        table.resizeRowsToContents()

        close_button = QPushButton(tr("help.shortcuts.close"), dialog)
        close_button.clicked.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        dialog.resize(360, table.height() + 70)
        dialog.exec()

    # ---------------------------------------------------------- window state
    def _restore_geometry(self) -> None:
        encoded = self._config_manager.config.window_geometry
        if encoded:
            try:
                self.restoreGeometry(base64.b64decode(encoded))
            except (ValueError, TypeError):
                logger.warning("Ignoring corrupt window geometry in config")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        self._config_manager.config.window_geometry = base64.b64encode(
            bytes(self.saveGeometry())).decode("ascii")
        # 持久化裁切框位置：下次启动时恢复到上次的归一化位置。
        self._config_manager.config.last_crop_relative = _format_relative(
            self._last_crop_relative)
        self._config_manager.save()
        localization.unsubscribe(self.retranslate_ui)
        super().closeEvent(event)
