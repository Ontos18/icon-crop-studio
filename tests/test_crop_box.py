"""Unit tests for models.crop_box (no Qt required)."""
from __future__ import annotations

import pytest

from models.crop_box import (
    CropBoxModel, CropState, reduce_aspect, wrap_max_k,
)


def _model(w: int = 800, h: int = 600,
           aspect: tuple[int, int] = (1, 1),
           wrap: bool = False) -> CropBoxModel:
    return CropBoxModel(w, h, aspect=aspect, wrap=wrap)


# ------------------------------------------------------------- 默认与基础
def test_default_square_is_max_top_left() -> None:
    m = _model(800, 600)
    assert m.state == CropState(0, 0, 600, 600)
    m2 = _model(300, 500)
    assert m2.state == CropState(0, 0, 300, 300)


def test_aspect_2x1_default_fits_image() -> None:
    m = _model(800, 600, aspect=(2, 1))
    # 最大满足 2:1 且不超出 800x600 的矩形 = 800x400
    assert m.state == CropState(0, 0, 800, 400)


def test_aspect_1x2_default_fits_image() -> None:
    m = _model(800, 600, aspect=(1, 2))
    assert m.state == CropState(0, 0, 300, 600)


def test_invalid_image_size_rejected() -> None:
    with pytest.raises(ValueError):
        CropBoxModel(0, 100)
    with pytest.raises(ValueError):
        CropBoxModel(100, 0)


def test_invalid_aspect_rejected() -> None:
    with pytest.raises(ValueError):
        CropBoxModel(100, 100, aspect=(0, 1))


def test_tiny_image_min_size_adapts() -> None:
    m = CropBoxModel(8, 8)
    assert m.min_size == 8
    assert m.state == CropState(0, 0, 8, 8)


def test_reduce_aspect() -> None:
    assert reduce_aspect(100, 200) == (1, 2)
    assert reduce_aspect(800, 800) == (1, 1)
    assert reduce_aspect(3, 5) == (3, 5)


# ------------------------------------------------------------- 移动与设置
def test_move_clamps_to_bounds() -> None:
    m = _model(800, 600)
    m.set_state(CropState(0, 0, 100, 100))
    m.move_by(-50, -50)
    assert m.state == CropState(0, 0, 100, 100)
    m.move_by(10_000, 10_000)
    assert m.state == CropState(700, 500, 100, 100)


def test_move_keeps_aspect() -> None:
    m = _model(800, 600, aspect=(1, 2))
    m.move_by(10_000, 10_000)
    s = m.state
    assert s.w / s.h == 0.5 and (s.w, s.h) == (300, 600)
    assert s.x == 800 - 300 and s.y == 0


def test_set_state_clamps_foreign_state() -> None:
    m = _model(200, 200)
    m.set_state(CropState(500, 500, 999, 999))
    assert m.state == CropState(0, 0, 200, 200)
    m.set_state(CropState(150, 150, 100, 100))
    assert m.state == CropState(100, 100, 100, 100)


def test_set_state_wrong_aspect_keeps_shape() -> None:
    """外来状态比例与当前不同：忽略其形状，只采纳位置并夹取。"""
    m = _model(800, 600, aspect=(2, 1))
    m.set_state(CropState(100, 100, 200, 100))   # 先设一个 2:1 小框
    m.set_state(CropState(50, 60, 300, 300))     # 3:3 与 2:1 不同 → 忽略形状
    s = m.state
    assert reduce_aspect(s.w, s.h) == (2, 1)
    assert (s.x, s.y) == (50, 60)


# ------------------------------------------------------------- 角点缩放
def test_resize_corner_br_anchors_top_left() -> None:
    m = _model(800, 600)
    m.set_state(CropState(100, 100, 200, 200))
    m.resize_corner("br", 50, 10)          # dominant axis = x
    assert m.state == CropState(100, 100, 250, 250)


def test_resize_corner_tl_anchors_bottom_right() -> None:
    m = _model(800, 600)
    m.set_state(CropState(100, 100, 200, 200))  # bottom-right at (300, 300)
    m.resize_corner("tl", -50, 0)          # grow toward top-left
    s = m.state
    assert s.w == 250
    assert (s.x + s.w, s.y + s.h) == (300, 300)


def test_resize_corner_keeps_aspect() -> None:
    m = _model(800, 600, aspect=(2, 1))
    m.set_state(CropState(100, 100, 200, 100))
    m.resize_corner("br", 200, 0)          # 向右拖 200px
    s = m.state
    assert reduce_aspect(s.w, s.h) == (2, 1)
    assert s == CropState(100, 100, 400, 200)


def test_resize_corner_respects_image_bounds() -> None:
    m = _model(400, 400)
    m.set_state(CropState(300, 300, 100, 100))
    m.resize_corner("br", 500, 500)        # would overflow
    assert m.state == CropState(300, 300, 100, 100)


def test_resize_corner_respects_min_size() -> None:
    m = _model(400, 400)
    m.set_state(CropState(0, 0, 100, 100))
    m.resize_corner("br", -95, -95)
    assert m.state.w >= m.min_size and m.state.h >= m.min_size


# ------------------------------------------------------------- 边缘缩放
def test_resize_edge_l_anchors_right() -> None:
    m = _model(800, 600)
    m.set_state(CropState(200, 100, 200, 200))  # right edge at x=400
    m.resize_edge("l", 50)
    s = m.state
    assert s.w == 250
    assert s.x + s.w == 400


def test_resize_edge_keeps_aspect() -> None:
    m = _model(800, 600, aspect=(1, 2))
    m.resize_edge("b", 100)               # grow downward
    s = m.state
    assert reduce_aspect(s.w, s.h) == (1, 2)


# ------------------------------------------------------------- 中心缩放
def test_resize_centered_keeps_center() -> None:
    m = _model(800, 600)
    m.set_state(CropState(200, 200, 200, 200))  # center (300, 300)
    m.resize_centered(100)
    s = m.state
    assert s.w == 300
    assert (s.x + s.w / 2, s.y + s.h / 2) == (300.0, 300.0)


def test_resize_centered_clamps_position_at_border() -> None:
    m = _model(800, 600)
    m.set_state(CropState(0, 0, 100, 100))      # center near corner
    m.resize_centered(200)
    s = m.state
    assert s.w == 300
    assert s.x >= 0 and s.y >= 0


# ------------------------------------------------------------- 比例切换
def test_set_aspect_keeps_center() -> None:
    m = _model(800, 600)
    m.set_state(CropState(200, 200, 200, 200))  # center (300, 300)
    m.set_aspect((2, 1))
    s = m.state
    assert reduce_aspect(s.w, s.h) == (2, 1)
    assert (s.x + s.w / 2, s.y + s.h / 2) == (300.0, 300.0)


def test_set_aspect_same_ratio_is_noop() -> None:
    m = _model(800, 600)
    m.set_state(CropState(100, 100, 200, 200))
    m.set_aspect((2, 2))                   # same as (1, 1)
    assert m.state == CropState(100, 100, 200, 200)


def test_set_aspect_extreme_ratio_clamps_to_fit() -> None:
    m = _model(100, 1000, aspect=(1, 1))
    m.set_aspect((1, 100))
    s = m.state
    assert reduce_aspect(s.w, s.h) == (1, 100)
    assert s.x >= 0 and s.y >= 0
    assert s.x + s.w <= 100 and s.y + s.h <= 1000


# ------------------------------------------------------------- 重置
def test_reset_restores_default() -> None:
    m = _model(800, 600)
    m.set_state(CropState(50, 50, 100, 100))
    assert m.reset() == CropState(0, 0, 600, 600)
    m2 = _model(800, 600, aspect=(2, 1))
    m2.set_state(CropState(50, 50, 100, 100))
    assert m2.reset() == CropState(0, 0, 800, 400)


def test_unknown_handles_rejected() -> None:
    m = _model()
    with pytest.raises(ValueError):
        m.resize_corner("xx", 1, 1)
    with pytest.raises(ValueError):
        m.resize_edge("xx", 1)


# ------------------------------------------------------------- 包裹模式
def test_wrap_max_k_covers_image() -> None:
    assert wrap_max_k(1200, 600, (1, 1)) == 1200
    assert wrap_max_k(600, 1200, (1, 1)) == 1200
    assert wrap_max_k(1200, 600, (1, 2)) == 1200
    assert wrap_max_k(100, 50, (2, 1)) == 50
    assert wrap_max_k(10, 10, (3, 5)) == 4
    assert wrap_max_k(800, 800, (1, 1)) == 800


def test_wrap_defaults_off() -> None:
    assert _model().wrap is False
    assert CropBoxModel(100, 100, wrap=True).wrap is True


def test_wrap_fit_horizontal_centers() -> None:
    m = _model(1200, 600)
    m.set_wrap(True)     # 开启只切换边界；wrap_fit 才做最大化+居中
    s = m.wrap_fit()
    assert s == CropState(0, -300, 1200, 1200)   # 宽边对齐，上下扩展
    assert m.wrap is True


def test_wrap_fit_vertical_centers() -> None:
    m = _model(600, 1200)
    s = m.wrap_fit()
    assert s == CropState(-300, 0, 1200, 1200)   # 高边对齐，左右扩展


def test_wrap_fit_non_square_aspect() -> None:
    m = _model(1200, 600, aspect=(1, 2))
    s = m.wrap_fit()
    assert s == CropState(0, -900, 1200, 2400)   # k=1200 → 1200×2400


def test_wrap_reset_returns_max_box_centered() -> None:
    m = _model(1200, 600, wrap=True)
    assert m.reset() == CropState(0, -300, 1200, 1200)


def test_wrap_max_box_is_pinned_to_canvas() -> None:
    """最大包裹框与画布（灰色区域）重合：移动无效果，锁死居中。"""
    m = _model(1200, 600)
    s = m.wrap_fit()                          # (0, -300, 1200, 1200) = 画布
    m.move_by(10_000, 10_000)
    m.move_by(-10_000, -10_000)
    assert m.state == s


def test_wrap_resize_capped_at_wrap_max() -> None:
    m = _model(1200, 600)
    m.wrap_fit()                          # 已达最大
    m.resize_corner("br", 1000, 1000)
    assert m.state == CropState(0, -300, 1200, 1200)
    m.resize_centered(500)
    assert m.state == CropState(0, -300, 1200, 1200)


def test_wrap_off_clamps_back_inside_image() -> None:
    m = _model(1200, 600)
    m.wrap_fit()
    m.set_wrap(False)
    s = m.state
    assert s.x >= 0 and s.y >= 0
    assert s.x + s.w <= 1200 and s.y + s.h <= 600


def test_wrap_shrunk_box_stays_in_canvas() -> None:
    """缩小后的框只能在灰色画布内活动：可自由移动，但不得越出画布。"""
    m = _model(1200, 600)
    m.wrap_fit()                              # 画布 (0, -300, 1200, 1200)
    m.resize_centered(-600)                   # 缩到 600x600
    m.move_by(10_000, 10_000)                 # 尝试拖出画布
    s = m.state
    assert (s.x, s.y) == (600, 300)           # 钳到画布右下角
    assert s.x + s.w == 1200 and s.y + s.h == 900   # 右/底边贴画布边界
    m.move_by(-10_000, -10_000)               # 尝试拖到另一端
    s2 = m.state
    assert (s2.x, s2.y) == (0, -300)          # 钳到画布左上角
    assert s2.x + s2.w == 600 and s2.y + s2.h == 300
