"""Left pane: input folder row, paged thumbnail grid, page controls."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QIcon, QImage, QPainter, QPalette, QPixmap, QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from core.localization import tr
from core.thumbnail_cache import ThumbnailCache
from models.image_collection import ImageCollection
from models.image_item import ImageStatus

logger = logging.getLogger(__name__)

_GLOBAL_INDEX_ROLE = Qt.ItemDataRole.UserRole
_STATUS_COLORS: dict[ImageStatus, str] = {
    ImageStatus.UNPROCESSED: "#9e9e9e",   # gray
    ImageStatus.PROCESSING: "#1976d2",    # blue
    ImageStatus.EXPORTED: "#2e7d32",      # green
    ImageStatus.FAILED: "#c62828",        # red
}


class _StatusBadgeDelegate(QStyledItemDelegate):
    """在默认 item 渲染之上实时叠加状态角标。

    角标颜色每次绘制时都从 collection 读取最新的 item.status，因此导出
    完成后只需触发 viewport 重绘即可刷新角标——绕开了
    ``QListWidgetItem.setIcon`` 在部分 PySide6 环境下不生效的问题。
    """

    def __init__(self, collection: ImageCollection,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._collection = collection

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        super().paint(painter, option, index)
        gi = index.data(_GLOBAL_INDEX_ROLE)
        if gi is None or not 0 <= gi < len(self._collection):
            return
        status = self._collection.items[gi].status
        # 用 list 的 iconSize 定位缩略图矩形（IconMode 下 icon 水平居中、
        # 顶部对齐），比 SE_ItemViewItemDecoration 更可靠。
        icon_w = icon_h = 96
        if option.widget is not None:
            s = option.widget.iconSize()
            icon_w, icon_h = s.width(), s.height()
        x = option.rect.x() + (option.rect.width() - icon_w) // 2
        y = option.rect.top()
        radius = max(4, icon_w // 16)
        margin = 2
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_STATUS_COLORS[status]))
        painter.drawEllipse(
            x + icon_w - 2 * radius - margin, y + margin,
            2 * radius, 2 * radius)


class _PagedListWidget(QListWidget):
    """List that turns wheel-at-the-edge into page flips."""

    page_flip_requested = Signal(int)   # +1 next page, -1 previous page

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y()
        if delta < 0 and bar.value() >= bar.maximum():
            self.page_flip_requested.emit(+1)
            event.accept()
            return
        if delta > 0 and bar.value() <= bar.minimum():
            self.page_flip_requested.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)


class ThumbnailPanel(QWidget):
    """Shows one page of ``ImageCollection`` as a thumbnail grid.

    The page capacity is ADAPTIVE: it is recomputed from the panel's
    current size so a page always fits completely — no scrolling, ever.
    Images that don't fit simply go to the next page (user request).

    Emits ``image_activated(global_index)`` when the user picks an image;
    the panel itself never mutates the collection's selection — that is
    MainWindow's job (single owner of application state).
    """

    image_activated = Signal(int)
    input_dir_changed = Signal(str)

    def __init__(self, collection: ImageCollection, cache: ThumbnailCache,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collection = collection
        self._cache = cache
        self._cache.thumbnail_ready.connect(self._on_thumbnail_ready)
        #: path str -> list item currently displayed (current page only)
        self._visible_items: dict[str, QListWidgetItem] = {}

        # Debounced page-capacity recomputation on resize.
        self._capacity_timer = QTimer(self)
        self._capacity_timer.setSingleShot(True)
        self._capacity_timer.setInterval(80)
        self._capacity_timer.timeout.connect(self._recompute_capacity)

        self._build_ui()
        self._list.viewport().installEventFilter(self)
        self.refresh()

    # --------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        from ui.widgets.path_picker import PathPicker

        self.input_picker = PathPicker(
            "panel.thumbnails.input_dir", "dialog.open_dir.title", self)
        self.input_picker.path_changed.connect(self.input_dir_changed)

        self._list = _PagedListWidget(self)
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setUniformItemSizes(True)
        self._list.setWordWrap(True)
        # A page always fits entirely -> scrollbars are never needed.
        self._list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_icon_size()
        # 状态角标由 delegate 实时绘制（导出完成后触发重绘即刷新）。
        self._list.setItemDelegate(
            _StatusBadgeDelegate(self._collection, self._list))
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.page_flip_requested.connect(self._on_page_flip)

        self._prev_button = QPushButton(self)
        self._prev_button.clicked.connect(lambda: self._change_page(-1))
        self._next_button = QPushButton(self)
        self._next_button.clicked.connect(lambda: self._change_page(+1))
        self._page_label = QLabel(self)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nav = QHBoxLayout()
        nav.setContentsMargins(4, 2, 4, 2)
        nav.addWidget(self._prev_button)
        nav.addWidget(self._page_label, 1)
        nav.addWidget(self._next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.input_picker)
        layout.addWidget(self._list, 1)
        layout.addLayout(nav)

    def _apply_icon_size(self) -> None:
        size = self._cache.thumbnail_size
        self._list.setIconSize(QSize(size, size))
        self._list.setGridSize(QSize(size + 24, size + 40))

    # ---------------------------------------------------- adaptive capacity
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._list.viewport() and event.type() == QEvent.Type.Resize:
            self._capacity_timer.start()
        return super().eventFilter(watched, event)

    def _recompute_capacity(self) -> None:
        """Fit page size to the visible area: capacity = columns × rows."""
        grid = self._list.gridSize()
        viewport = self._list.viewport().size()
        columns = max(1, viewport.width() // grid.width())
        rows = max(1, viewport.height() // grid.height())
        capacity = columns * rows
        if capacity == self._collection.page_size:
            return
        # Keep the first currently-visible image visible after the change.
        anchor = self._collection.current_page * self._collection.page_size
        self._collection.set_page_size(capacity)
        self._collection.go_to_page(anchor // capacity)
        self.refresh()

    # ------------------------------------------------------------------ API
    def refresh(self) -> None:
        """Rebuild the list for the collection's current page."""
        self._list.clear()
        self._visible_items.clear()
        for global_index, item in self._collection.items_on_page():
            list_item = QListWidgetItem(item.name)
            list_item.setData(_GLOBAL_INDEX_ROLE, global_index)
            list_item.setToolTip(str(item.path))
            list_item.setIcon(QIcon(self._placeholder_icon()))
            self._list.addItem(list_item)
            self._visible_items[str(item.path)] = list_item
            self._cache.request(item.path)
        self._sync_selection_highlight()
        self._update_nav()

    def sync_selection(self) -> None:
        """Called by MainWindow after the collection selection changed."""
        self._sync_selection_highlight()

    def set_thumbnail_size(self, size: int) -> None:
        """Change the grid's thumbnail size (settings dialog).

        Invalidates the cache (different-size thumbnails are useless), then
        recomputes the adaptive page capacity and rebuilds the page.
        """
        self._cache.set_thumbnail_size(size)
        self._apply_icon_size()
        self._recompute_capacity()
        self.refresh()

    def retranslate_ui(self) -> None:
        self.input_picker.retranslate_ui()
        self._update_nav()

    # ------------------------------------------------------------- internal
    def _update_nav(self) -> None:
        self._page_label.setText(tr(
            "panel.thumbnails.page",
            current=self._collection.current_page + 1,
            total=self._collection.page_count))
        self._prev_button.setText(tr("panel.thumbnails.prev_page"))
        self._next_button.setText(tr("panel.thumbnails.next_page"))
        self._prev_button.setEnabled(self._collection.current_page > 0)
        self._next_button.setEnabled(
            self._collection.current_page < self._collection.page_count - 1)

    def _change_page(self, step: int) -> None:
        moved = (self._collection.next_page() if step > 0
                 else self._collection.prev_page())
        if moved:
            self.refresh()

    def _on_page_flip(self, step: int) -> None:
        self._change_page(step)

    def _on_item_clicked(self, list_item: QListWidgetItem) -> None:
        self.image_activated.emit(list_item.data(_GLOBAL_INDEX_ROLE))

    def _sync_selection_highlight(self) -> None:
        current = self._collection.current_index
        for row in range(self._list.count()):
            list_item = self._list.item(row)
            if list_item.data(_GLOBAL_INDEX_ROLE) == current:
                self._list.setCurrentItem(list_item)
                return
        self._list.setCurrentItem(None)

    def _on_thumbnail_ready(self, key: str, image: QImage) -> None:
        list_item = self._visible_items.get(key)
        if list_item is None or image.isNull():
            return          # item scrolled off to another page meanwhile
        # icon 只存原始缩略图（无角标）；角标由 _StatusBadgeDelegate 在
        # 绘制时实时叠加，因此无需 setIcon 即可随状态变化刷新。
        list_item.setIcon(QIcon(QPixmap.fromImage(image)))
        self._list.viewport().update()

    def _placeholder_icon(self) -> QPixmap:
        size = self._cache.thumbnail_size
        pixmap = QPixmap(size, size)
        # 跟随主题底色，避免深色主题下占位块"闪白"。
        pixmap.fill(self.palette().color(QPalette.ColorRole.Base))
        return pixmap

    def update_status_badge(self, path: Path) -> None:
        """Re-render one item's badge after its status changed (Phase 6)."""
        key = str(path)
        if key in self._visible_items:
            # 触发重绘即可：delegate 读取最新 status 画角标。
            self._list.viewport().update()
