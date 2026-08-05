"""Live preview of the current crop at the selected export sizes (Phase 7).

Paints a checkerboard background (so alpha is visible) with one thumbnail
per selected output size (square or non-square), flow-wrapped, and the
pixel size labelled under each tile. The heavy decoding happens in a worker
thread (``core.preview_service``); this widget only stores the resulting
QImage and repaints — no image I/O on the GUI thread.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from core.localization import tr

_CHECKER = 8           # checkerboard cell size in px
_PADDING = 6           # outer margin in px
_GAP = 10              # horizontal space between tiles
_DISPLAY_MAX = 128     # 预览 tile 长边上限（大尺寸等比例缩到该值以内）


class CropPreview(QWidget):
    """Checkerboard + per-size tiles of the current crop."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._sizes: list[tuple[int, int]] = []

    # ------------------------------------------------------------------ API
    def set_preview(self, image: QImage, sizes: list[tuple[int, int]]) -> None:
        """Show ``image`` scaled to each (w, h) in ``sizes`` (null = clear)."""
        self._image = None if image.isNull() else image
        self._sizes = list(sizes)
        self.update()

    def clear(self) -> None:
        self._image = None
        self._sizes = []
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._image is None:
            # 占位提示：浅色主题用纯黑、深色主题用浅色，保证高对比度。
            if self.palette().window().color().lightness() < 128:
                painter.setPen(QColor(232, 232, 232))
            else:
                painter.setPen(QColor(0, 0, 0))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             tr("panel.export.preview"))
            return
        self._paint_checkerboard(painter)
        self._paint_tiles(painter)

    def _paint_checkerboard(self, painter: QPainter) -> None:
        # 跟随主题：深色主题下用深棋盘格，否则尺寸标签文字（windowText）
        # 会以浅色落在浅色棋盘格上看不清。
        if self.palette().window().color().lightness() < 128:
            light, dark = QColor("#5a5a5a"), QColor("#464646")
        else:
            light, dark = QColor("#ffffff"), QColor("#e2e2e2")
        rect = self.rect()
        for y in range(rect.top(), rect.bottom(), _CHECKER):
            for x in range(rect.left(), rect.right(), _CHECKER):
                odd = ((x // _CHECKER) + (y // _CHECKER)) % 2
                painter.fillRect(x, y, _CHECKER, _CHECKER,
                                 dark if odd else light)

    def _paint_tiles(self, painter: QPainter) -> None:
        fm = self.fontMetrics()
        label_h = fm.height() + 2
        x, y = _PADDING, _PADDING
        row_height = 0
        max_x = self.width() - _PADDING
        source = QPixmap.fromImage(self._image)
        for w, h in sorted(self._sizes, key=lambda s: max(s), reverse=True):
            # 大尺寸按比例缩到显示上限，小尺寸原样显示。
            scale = min(1.0, _DISPLAY_MAX / max(w, h))
            tile_w = max(1, round(w * scale))
            tile_h = max(1, round(h * scale))
            if x + tile_w > max_x and x > _PADDING:   # flow-wrap
                x = _PADDING
                y += row_height
                row_height = 0
            scaled = source.scaled(tile_w, tile_h,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int(x), int(y), scaled)
            painter.setPen(QPen(QColor(0, 0, 0, 80)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(x, y, tile_w, tile_h))
            painter.setPen(self.palette().windowText().color())
            label = f"{w}" if w == h else f"{w}x{h}"
            painter.drawText(int(x), int(y + tile_h + 2 + fm.ascent()), label)
            x += tile_w + _GAP
            row_height = max(row_height, tile_h + label_h)
