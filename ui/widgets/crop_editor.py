"""Center pane: QGraphicsView-based square crop editor.

Interaction summary
-------------------
* drag inside the box .......... move (always square, never leaves image)
* drag corner/edge handles ..... resize (opposite corner/edge anchored)
* W/A/S/D ...................... nudge box (Shift = fast, Ctrl = fine)
* Shift + wheel ............... grow / shrink box around center
* Esc (rebindable) ............. reset to default box (configurable action)
* Ctrl + wheel ................. zoom canvas (anchored under cursor)
* middle-button drag ........... pan canvas
* double click ................. fit image to window
* Ctrl+Z / Ctrl+Y .............. undo / redo (via MainWindow actions)

All geometry math is delegated to the Qt-free ``CropBoxModel``; this class
only translates input events and paints the overlay.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QObject, QPointF, QRunnable, QRectF, Qt, QThreadPool, QTimer, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QImage, QImageReader, QKeyEvent, QMouseEvent, QPainter,
    QPainterPath, QPen, QPixmap, QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEffect, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
)

from core.localization import tr
from core.undo_redo import UndoStack
from models.crop_box import CropBoxModel, CropState, wrap_max_k

logger = logging.getLogger(__name__)


class _LoadSignals(QObject):
    """QRunnable 不能持有 Signal，用这个小 QObject 承载。"""
    loaded = Signal(object, int, QImage)   # path, generation, image


class _ImageLoadTask(QRunnable):
    """在后台线程全尺寸解码一张图片（含 EXIF 旋转）。"""

    def __init__(self, path: Path, generation: int,
                 signals: _LoadSignals) -> None:
        super().__init__()
        self._path = path
        self._generation = generation
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        image = QImage()
        try:
            reader = QImageReader(str(self._path))
            reader.setAutoTransform(True)
            image = reader.read()
        except Exception:                        # never kill the pool
            logger.exception("Image decode failed for %s", self._path)
        self._signals.loaded.emit(self._path, self._generation, image)


class _BrightnessEffect(QGraphicsEffect):
    """通过叠加半透明白/黑模拟亮度调整（不修改源图像）。

    ``value`` 范围 -100（全暗）~ 100（全亮），0 为原图。用 fillRect 叠加
    纯色，GPU 加速，滑块拖动时开销很小。
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._brightness = 0

    def set_brightness(self, value: int) -> None:
        value = max(-100, min(100, int(value)))
        if value != self._brightness:
            self._brightness = value
            self.update()

    def brightness(self) -> int:
        return self._brightness

    def draw(self, painter: QPainter) -> None:  # noqa: N802 (Qt API)
        self.drawSource(painter)
        value = self._brightness
        if value == 0:
            return
        alpha = int(abs(value) * 255 // 100)
        color = (QColor(255, 255, 255, alpha) if value > 0
                 else QColor(0, 0, 0, alpha))
        painter.fillRect(self.boundingRect(), color)

_ZOOM_MIN = 0.05
_ZOOM_MAX = 32.0
_ZOOM_STEP = 1.25
_HANDLE_VIEW_PX = 8          # handle square size, in *view* pixels
_GRAB_TOLERANCE_PX = 6       # extra grab slack around handles/edges

#: keyboard nudge step: base = configurable (default 10), Shift = ×4,
#: Ctrl = fine 1px. WASD moves; Shift+滚轮按此步长缩放裁切框。
_STEP_FAST_MULTIPLIER = 4
_STEP_FINE = 1

_CURSORS: dict[str, Qt.CursorShape] = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "inside": Qt.CursorShape.SizeAllCursor,
}


class CropEditor(QGraphicsView):
    """Displays one image with an always-square, always-inside crop box."""

    crop_changed = Signal(object)          # CropState
    undo_available = Signal(bool)
    redo_available = Signal(bool)
    image_loaded = Signal(object)          # Path：图片解码完成并显示

    #: 最近解码的图片缓存容量（大图占内存，只留几张小容量足够来回切换）。
    _IMAGE_CACHE_MAX = 3

    def __init__(self, parent=None, *, move_speed: int = 10,  # noqa: ANN001
                 wheel_resize_step: int = 100,
                 wheel_zoom_step: float = _ZOOM_STEP) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._model: CropBoxModel | None = None
        self._undo: UndoStack[CropState] = UndoStack()
        #: 显示亮度值（-100~100，0 为原图）；effect 会被 scene.clear() 删除，
        #: 因此亮度值单独保存，切图/清空时重建 effect 并恢复。
        self._brightness = 0
        self._brightness_effect = _BrightnessEffect(self)
        #: 异步图片解码：一次一张，generation 丢弃过期结果；缓存最近几张。
        self._load_pool = QThreadPool(self)
        self._load_pool.setMaxThreadCount(1)
        self._load_generation = 0
        self._load_signals = _LoadSignals()
        self._load_signals.loaded.connect(self._on_image_decoded)
        self._image_cache: OrderedDict[str, QImage] = OrderedDict()
        #: 当前裁切框的宽高比 (aw, ah)，由所选输出尺寸推导。
        self._aspect: tuple[int, int] = (1, 1)
        #: 包裹模式：裁切框可越过图片边界，图片外的场景区域标识填充区。
        self._wrap_mode = False
        #: WASD 每步移动的像素数（无修饰键时）。
        self._move_speed = max(1, int(move_speed))
        #: Shift+滚轮缩放裁切框的每格步长（像素）。
        self._wheel_resize_step = max(1, int(wheel_resize_step))
        #: Ctrl+滚轮缩放画布的每格倍率（>1）。
        self._wheel_zoom_step = max(1.01, float(wheel_zoom_step))
        #: 窗口首次显示前加载的图片，viewport 尺寸未就绪，fit 结果会很小；
        #: 首次 showEvent 时重新 fit 一次（见 showEvent）。
        self._ever_shown = False

        # interaction state
        self._drag_mode: str | None = None      # handle name / "inside" / None
        self._drag_last: QPointF = QPointF()
        self._pan_last: QPointF | None = None
        self._drag_moved = False

        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(self.palette().window())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ================================================================== API
    def set_image(self, path: Path) -> bool:
        """异步加载 ``path`` 全尺寸；解码完成后显示并发射 image_loaded。

        解码在后台线程进行，切图不再阻塞 UI。图片加载完成前保留旧图，
        ``image_loaded`` 信号用于通知 MainWindow 应用位置记忆与预览。
        返回 True 表示请求已提交（不代表解码成功）。
        """
        key = str(path)
        cached = self._image_cache.get(key)
        if cached is not None:
            self._image_cache.move_to_end(key)
            self._display_decoded_image(path, cached)
            self.image_loaded.emit(path)
            return True
        self._load_generation += 1
        self._load_pool.start(_ImageLoadTask(
            path, self._load_generation, self._load_signals))
        return True

    def _display_decoded_image(self, path: Path, image: QImage) -> None:
        """把已解码的图片放上场景、重置裁切框并 fit 窗口。"""
        self._scene.clear()
        self._rebuild_brightness_effect()   # scene.clear() 删除了旧 effect
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(image))
        self._pixmap_item.setGraphicsEffect(self._brightness_effect)
        self._model = CropBoxModel(
            image.width(), image.height(), aspect=self._aspect,
            wrap=self._wrap_mode)
        self._model.reset()
        self._undo.reset(self._model.state)
        self._update_scene_rect()
        self.fit_to_window()
        # 不发射 crop_changed：这是程序性重置，位置记忆等逻辑由 MainWindow
        # 通过 image_loaded 信号自行处理。
        self._emit_history_state()
        self.viewport().update()

    def _on_image_decoded(self, path: Path, generation: int,
                          image: QImage) -> None:
        """后台解码完成（GUI 线程）；过期结果直接丢弃。"""
        if generation != self._load_generation:
            logger.debug("Discarding stale decode for %s", path)
            return
        if image.isNull():
            logger.warning("Failed to load %s", path)
            self.clear()
            return
        if len(self._image_cache) >= self._IMAGE_CACHE_MAX:
            self._image_cache.popitem(last=False)
        self._image_cache[str(path)] = image
        self._display_decoded_image(path, image)
        self.image_loaded.emit(path)

    def apply_initial_state(self, state: CropState) -> None:
        """Seed the crop box (auto-remember for same-sized images)."""
        if self._model is None:
            return
        self._model.set_state(state)
        self._undo.reset(self._model.state)
        self._notify(push=False)

    def clear(self) -> None:
        self._scene.clear()
        self._rebuild_brightness_effect()   # scene.clear() 删除了旧 effect
        self._pixmap_item = None
        self._model = None
        self._emit_history_state()
        self.viewport().update()

    def current_state(self) -> CropState | None:
        return self._model.state if self._model is not None else None

    def image_size(self) -> tuple[int, int] | None:
        return self._model.image_size if self._model is not None else None

    @property
    def aspect(self) -> tuple[int, int]:
        """当前裁切框的宽高比 (aw, ah)。"""
        return self._aspect

    def has_image(self) -> bool:
        return self._model is not None

    def set_move_speed(self, speed: int) -> None:
        """更新 WASD 键盘步进速度（设置对话框修改后调用）。"""
        self._move_speed = max(1, int(speed))

    def set_wheel_resize_step(self, step: int) -> None:
        """更新 Shift+滚轮缩放裁切框的每格步长（像素）。"""
        self._wheel_resize_step = max(1, int(step))

    def set_wheel_zoom_step(self, zoom_step: float) -> None:
        """更新 Ctrl+滚轮缩放画布的每格倍率（>1）。"""
        self._wheel_zoom_step = max(1.01, float(zoom_step))

    def set_brightness(self, value: int) -> None:
        """调整显示亮度（-100 暗 ~ 100 亮，0 为原图）。"""
        self._brightness = max(-100, min(100, int(value)))
        self._brightness_effect.set_brightness(self._brightness)

    def brightness(self) -> int:
        return self._brightness

    def _rebuild_brightness_effect(self) -> None:
        """scene.clear() 会删除挂在图片上的 effect，这里重建并恢复亮度。"""
        self._brightness_effect = _BrightnessEffect(self)
        self._brightness_effect.set_brightness(self._brightness)

    def set_aspect(self, w: int, h: int) -> None:
        """切换裁切框宽高比（输出尺寸比例变化时调用）。

        当前已加载图片时即时切换比例并尽量保持中心；否则仅记录，等
        下一张图片加载时生效。
        """
        if w < 1 or h < 1:
            return
        self._aspect = (w, h)
        if self._model is not None:
            self._model.set_aspect((w, h))
            self._update_scene_rect()
            self._notify()

    def set_wrap_mode(self, wrap: bool) -> None:
        """切换包裹模式。

        开启：裁切框自动变为能完全包裹图片的最大框并居中（wrap_fit）。
        关闭：把越界裁切框缩回图片内。无图片时仅记录状态，图片加载时
        生效。切换会 push 一个撤销快照（Ctrl+Z 可撤销几何变化）。
        """
        wrap = bool(wrap)
        if wrap == self._wrap_mode:
            return
        self._wrap_mode = wrap
        if self._model is None:
            return
        if wrap:
            self._model.wrap_fit()
        else:
            self._model.set_wrap(False)
        self._update_scene_rect()
        self._notify()
        self.fit_to_window()

    @property
    def wrap_mode(self) -> bool:
        return self._wrap_mode

    def _update_scene_rect(self) -> None:
        """根据模式设置场景矩形。

        普通模式：场景 = 图片矩形。包裹模式：扩展到能容纳最大包裹框的
        区域（以图片中心为基准），让用户能看到裁切框在图片外的填充区。
        """
        if self._pixmap_item is None:
            return
        base = QRectF(self._pixmap_item.pixmap().rect())
        if self._wrap_mode and self._model is not None:
            aw, ah = self._model.aspect
            k = wrap_max_k(int(base.width()), int(base.height()), (aw, ah))
            w, h = k * aw, k * ah
            center = base.center()
            canvas = QRectF(center.x() - w / 2, center.y() - h / 2, w, h)
            self._scene.setSceneRect(base.united(canvas))
        else:
            self._scene.setSceneRect(base)

    def fit_to_window(self) -> None:
        if self._pixmap_item is None:
            return
        # 包裹模式下以场景矩形为锚点（能看到图片外的填充区）；普通模式下
        # 场景矩形即图片矩形，等价于 fit 图片本身。
        self.fitInView(self._scene.sceneRect(),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def reset_crop(self) -> None:
        if self._model is not None:
            self._model.reset()
            self._notify()

    def undo(self) -> None:
        state = self._undo.undo()
        if state is not None and self._model is not None:
            self._model.set_state(state)
            self._notify(push=False)

    def redo(self) -> None:
        state = self._undo.redo()
        if state is not None and self._model is not None:
            self._model.set_state(state)
            self._notify(push=False)

    def retranslate_ui(self) -> None:
        # 主题切换后 palette 变化：重设背景刷，否则画布仍是旧主题颜色。
        self.setBackgroundBrush(self.palette().window())
        self.viewport().update()      # repaints the "no image" hint text

    # ============================================================ internals
    def _notify(self, *, push: bool = True) -> None:
        """Repaint, optionally record history, and broadcast the new state."""
        if self._model is None:
            return
        if push:
            self._undo.push(self._model.state)
        self._emit_history_state()
        self.viewport().update()
        self.crop_changed.emit(self._model.state)

    def _emit_history_state(self) -> None:
        self.undo_available.emit(self._undo.can_undo)
        self.redo_available.emit(self._undo.can_redo)

    def _zoom_factor(self) -> float:
        return self.transform().m11()

    def _crop_rect_scene(self) -> QRectF:
        assert self._model is not None
        s = self._model.state
        return QRectF(s.x, s.y, s.w, s.h)

    def _hit_test(self, scene_pos: QPointF) -> str | None:
        """Which handle/area is under ``scene_pos``? (scene == image coords)"""
        if self._model is None:
            return None
        rect = self._crop_rect_scene()
        tol = (_HANDLE_VIEW_PX / 2 + _GRAB_TOLERANCE_PX) / self._zoom_factor()

        corners = {
            "tl": rect.topLeft(), "tr": rect.topRight(),
            "bl": rect.bottomLeft(), "br": rect.bottomRight(),
        }
        for name, point in corners.items():
            if (abs(scene_pos.x() - point.x()) <= tol
                    and abs(scene_pos.y() - point.y()) <= tol):
                return name

        near_l = abs(scene_pos.x() - rect.left()) <= tol
        near_r = abs(scene_pos.x() - rect.right()) <= tol
        near_t = abs(scene_pos.y() - rect.top()) <= tol
        near_b = abs(scene_pos.y() - rect.bottom()) <= tol
        within_x = rect.left() - tol <= scene_pos.x() <= rect.right() + tol
        within_y = rect.top() - tol <= scene_pos.y() <= rect.bottom() + tol
        if near_l and within_y:
            return "l"
        if near_r and within_y:
            return "r"
        if near_t and within_x:
            return "t"
        if near_b and within_x:
            return "b"
        if rect.contains(scene_pos):
            return "inside"
        return None

    # ------------------------------------------------------------ painting
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        if self._model is None:
            self._draw_empty_hint(painter)
            return
        # 包裹模式：图片外的场景区域标识为填充区（透明/白）。
        self._paint_fill_area(painter)
        crop = self._crop_rect_scene()
        image = QRectF(self._scene.sceneRect())

        # Dim everything outside the crop box.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        left = QRectF(image.left(), image.top(),
                      crop.left() - image.left(), image.height())
        right = QRectF(crop.right(), image.top(),
                       image.right() - crop.right(), image.height())
        top = QRectF(crop.left(), image.top(),
                     crop.width(), crop.top() - image.top())
        bottom = QRectF(crop.left(), crop.bottom(),
                        crop.width(), image.bottom() - crop.bottom())
        for region in (left, right, top, bottom):
            if region.isValid():
                painter.drawRect(region)

        # Crop border: cosmetic white line with a subtle dark outline so it
        # stays visible on both light and dark images.
        outline = QPen(QColor(0, 0, 0, 160))
        outline.setCosmetic(True)
        outline.setWidth(3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(outline)
        painter.drawRect(crop)
        border = QPen(QColor(255, 255, 255))
        border.setCosmetic(True)
        border.setWidth(1)
        painter.setPen(border)
        painter.drawRect(crop)

        # Handles (constant size on screen regardless of zoom).
        half = (_HANDLE_VIEW_PX / 2) / self._zoom_factor()
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0, 200)))
        for point in (crop.topLeft(), crop.topRight(), crop.bottomLeft(),
                      crop.bottomRight(),
                      QPointF(crop.center().x(), crop.top()),
                      QPointF(crop.center().x(), crop.bottom()),
                      QPointF(crop.left(), crop.center().y()),
                      QPointF(crop.right(), crop.center().y())):
            painter.drawRect(QRectF(point.x() - half, point.y() - half,
                                    2 * half, 2 * half))

    def _paint_fill_area(self, painter: QPainter) -> None:
        """包裹模式下，把图片外（场景内）的区域用棋盘格标识为填充区。"""
        if not self._wrap_mode or self._pixmap_item is None:
            return
        image = self._pixmap_item.boundingRect()
        painter.save()
        # 反向裁剪：只绘制 sceneRect 内、图片矩形外的部分。
        # Qt 的 ClipOperation 没有 ReverseClip 枚举，这里用 QPainterPath
        # 的 OddEven 规则实现等效的"挖洞"（两矩形重叠区被裁剪掉），
        # 并用 IntersectClip 保留 viewport 本身的裁剪限制。
        path = QPainterPath()
        path.addRect(self._scene.sceneRect())
        path.addRect(image)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        painter.fillRect(self._scene.sceneRect(), self._wrap_fill_brush())
        painter.restore()

    @staticmethod
    def _wrap_fill_brush() -> QBrush:
        """半透明棋盘格，表示透明填充区（深浅主题下均可见）。"""
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.fillRect(0, 0, 8, 8, QColor(255, 255, 255, 70))
        p.fillRect(8, 8, 8, 8, QColor(255, 255, 255, 70))
        p.fillRect(8, 0, 8, 8, QColor(0, 0, 0, 25))
        p.fillRect(0, 8, 8, 8, QColor(0, 0, 0, 25))
        p.end()
        return QBrush(pix)

    def _draw_empty_hint(self, painter: QPainter) -> None:
        painter.resetTransform()
        # 提示文字：浅色主题用纯黑、深色主题用浅色，保证高对比度。
        if self.palette().window().color().lightness() < 128:
            painter.setPen(QColor(232, 232, 232))
        else:
            painter.setPen(QColor(0, 0, 0))
        painter.drawText(self.viewport().rect(),
                         Qt.AlignmentFlag.AlignCenter, tr("panel.editor.empty"))

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._model:
            hit = self._hit_test(self.mapToScene(event.position().toPoint()))
            if hit is not None:
                self._drag_mode = hit
                self._drag_moved = False
                self._drag_last = self.mapToScene(event.position().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return

        if self._drag_mode is not None and self._model is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            dx = round(scene_pos.x() - self._drag_last.x())
            dy = round(scene_pos.y() - self._drag_last.y())
            if dx or dy:
                # Only consume the movement we actually applied, so the
                # box doesn't "lag behind" the cursor at image borders.
                self._drag_last = QPointF(self._drag_last.x() + dx,
                                          self._drag_last.y() + dy)
                self._drag_moved = True
                if self._drag_mode == "inside":
                    self._model.move_by(dx, dy)
                elif self._drag_mode in ("tl", "tr", "bl", "br"):
                    self._model.resize_corner(self._drag_mode, dx, dy)
                else:
                    edge_delta = {"l": -dx, "r": dx, "t": -dy, "b": dy}
                    self._model.resize_edge(
                        self._drag_mode, edge_delta[self._drag_mode])
                self._notify(push=False)     # history entry on release only
            event.accept()
            return

        # hover feedback
        if self._model is not None:
            hit = self._hit_test(self.mapToScene(event.position().toPoint()))
            self.setCursor(_CURSORS.get(hit, Qt.CursorShape.ArrowCursor)
                           if hit else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._drag_mode is not None:
            if self._drag_moved:
                self._notify()               # one undo step per drag gesture
            self._drag_mode = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.fit_to_window()
        event.accept()

    # ---------------------------------------------------------------- show
    def showEvent(self, event) -> None:  # noqa: ANN001, N802 (Qt API)
        super().showEvent(event)
        # 启动时自动加载的首图会在窗口显示前触发 fit_to_window，而彼时
        # viewport 尚未布局（可能只有 ~96×26px），会把图片缩到几乎看不见。
        # 首次显示时布局也未必完全就绪，因此用 singleShot(0) 等到事件循环
        # 中布局稳定后再 fit 一次校正。
        if not self._ever_shown:
            self._ever_shown = True
            if self._model is not None:
                QTimer.singleShot(0, self.fit_to_window)

    # --------------------------------------------------------------- wheel
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Shift+滚轮：居中缩放裁切框（上滚放大、下滚缩小），替代原 Q/E。
            if self._model is not None:
                step = self._wheel_resize_step
                if event.angleDelta().y() > 0:
                    self._model.resize_centered(step)
                else:
                    self._model.resize_centered(-step)
                self._notify()
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            factor = self._wheel_zoom_step if event.angleDelta().y() > 0 \
                else 1 / self._wheel_zoom_step
            new_zoom = self._zoom_factor() * factor
            if _ZOOM_MIN <= new_zoom <= _ZOOM_MAX:
                self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------ keyboard
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._model is None:
            super().keyPressEvent(event)
            return
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            step = self._move_speed * _STEP_FAST_MULTIPLIER
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            step = _STEP_FINE
        else:
            step = self._move_speed

        key = event.key()
        handled = True
        if key == Qt.Key.Key_W:
            self._model.move_by(0, -step)
        elif key == Qt.Key.Key_S:
            self._model.move_by(0, step)
        elif key == Qt.Key.Key_A:
            self._model.move_by(-step, 0)
        elif key == Qt.Key.Key_D:
            self._model.move_by(step, 0)
        # Esc is handled by the configurable action_reset_crop (Phase 5) so
        # the shortcut can be rebound in the settings dialog.
        else:
            handled = False

        if handled:
            self._notify()
            event.accept()
        else:
            super().keyPressEvent(event)
