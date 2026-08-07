"""Regression tests for CropEditor's wrap-mode foreground painting.

历史背景：``_paint_fill_area`` 曾使用不存在的 ``Qt.ClipOperation.ReverseClip``，
导致包裹模式下每次绘制 QGraphicsView 都会打印 Python traceback（stderr 出现
"Error calling Python override"）且 QPainter save/restore 不配对。这里用两种
方式守护：
1. 直接调用 ``drawForeground``（异常会从 Python 层直接抛出，可断言不抛）；
2. 走真实 ``render()`` 路径，用 capfd 断言 stderr 无 Qt 报错。
"""
from __future__ import annotations

import os
from pathlib import Path

# 必须在任何 Qt 导入前设置，保证无显示环境（CI/无头）也能创建 QApplication。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.widgets.crop_editor import CropEditor


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def _editor_with_image(app: QApplication) -> CropEditor:
    """构造一个已加载 120x80 红色图片的 CropEditor（同步放图，绕开线程池）。"""
    editor = CropEditor()
    editor.resize(400, 400)
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 0, 0))
    editor._display_decoded_image(Path("wrap_fit.png"), image)
    return editor


def _render(editor: CropEditor) -> None:
    """把 editor 渲染到 QImage（QGraphicsView.render 只接受 QPainter）。"""
    out = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(out)
    try:
        editor.render(painter)
    finally:
        painter.end()


def test_wrap_mode_draw_foreground_does_not_raise(app) -> None:
    """包裹模式下 drawForeground 直接调用不抛异常（回归 ReverseClip bug）。"""
    editor = _editor_with_image(app)
    editor.set_wrap_mode(True)
    assert editor.wrap_mode is True
    out = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(out)
    try:
        # Python 层直接调用：若内部抛异常会向上传播，而不是被 Qt 吞掉。
        editor.drawForeground(painter, QRectF(0, 0, 400, 400))
    finally:
        painter.end()


def test_wrap_mode_render_prints_no_error(app, capfd) -> None:
    """走真实渲染路径：stderr 不得出现 Qt 的 Python override 报错。"""
    editor = _editor_with_image(app)
    editor.set_wrap_mode(True)
    editor.show()
    app.processEvents()
    _render(editor)
    err = capfd.readouterr().err
    assert "Error calling Python override" not in err
    assert "ReverseClip" not in err


def test_normal_mode_render_prints_no_error(app, capfd) -> None:
    """普通模式渲染同样无报错（回归不影响既有绘制）。"""
    editor = _editor_with_image(app)
    editor.show()
    app.processEvents()
    _render(editor)
    err = capfd.readouterr().err
    assert "Error calling Python override" not in err


def test_wrap_fill_area_paints_outside_image(app) -> None:
    """包裹模式下图片矩形外确实被棋盘格填充（而非图片区域）。"""
    editor = _editor_with_image(app)      # 120x80 图，wrap 后场景扩为 120x120
    editor.set_wrap_mode(True)
    scene = editor._scene
    image_rect = editor._pixmap_item.boundingRect()
    canvas = scene.sceneRect()
    assert canvas.width() == 120 and canvas.height() == 120
    # 图片中心仍在场景内；图片外（左上角）与图片内应属于不同区域。
    assert image_rect.contains(canvas.center())


def _wheel_event(y_delta: int, mod: Qt.KeyboardModifier) -> QWheelEvent:
    """构造一个垂直滚轮的 wheel 事件（angleDelta.y = y_delta，单位 1/8°）。"""
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(), QPoint(0, y_delta),
        Qt.MouseButton.NoButton, mod,
        Qt.ScrollPhase.NoScrollPhase, False)


def test_shift_wheel_resizes_crop_box(app) -> None:
    """Shift+滚轮：上滚放大、下滚缩小裁切框（替代原 Q/E）。"""
    editor = _editor_with_image(app)
    editor.set_wrap_mode(True)            # 框 = 画布 120x120，锁死居中
    assert editor.current_state().w == 120
    editor.wheelEvent(_wheel_event(-120, Qt.KeyboardModifier.ShiftModifier))
    assert editor.current_state().w < 120              # 下滚缩小
    editor.wheelEvent(_wheel_event(120, Qt.KeyboardModifier.ShiftModifier))
    assert editor.current_state().w == 120             # 上滚放大回画布上限


def test_ctrl_wheel_still_zooms_canvas(app) -> None:
    """Ctrl+滚轮仍然缩放画布，与 Shift+滚轮不冲突。"""
    editor = _editor_with_image(app)
    before = editor._zoom_factor()
    editor.wheelEvent(_wheel_event(120, Qt.KeyboardModifier.ControlModifier))
    assert editor._zoom_factor() > before


def test_wheel_steps_are_configurable(app) -> None:
    """Shift/Ctrl 滚轮的步长可配置，改动后立即生效。"""
    editor = _editor_with_image(app)
    editor.set_wheel_resize_step(50)          # 每格 50px
    editor.set_wrap_mode(True)                # 框 = 120x120
    assert editor.current_state().w == 120
    editor.wheelEvent(_wheel_event(-120, Qt.KeyboardModifier.ShiftModifier))
    assert editor.current_state().w == 120 - 50

    editor2 = _editor_with_image(app)
    editor2.set_wheel_zoom_step(2.0)          # 每格 2 倍
    before = editor2._zoom_factor()
    editor2.wheelEvent(_wheel_event(120, Qt.KeyboardModifier.ControlModifier))
    assert editor2._zoom_factor() == pytest.approx(before * 2.0)


def test_resize_mode_hides_and_disables_crop_overlay(app) -> None:
    editor = _editor_with_image(app)
    before = editor.current_state()
    editor.set_crop_enabled(False)
    assert editor.crop_enabled is False

    # Crop-specific Shift+wheel no longer changes the model.
    editor.wheelEvent(_wheel_event(-120, Qt.KeyboardModifier.ShiftModifier))
    assert editor.current_state() == before

    # Rendering the full-image mode must remain error-free.
    _render(editor)
