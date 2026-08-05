"""Rectangular crop-box geometry in image pixel coordinates (Qt-free).

The box always keeps a fixed **aspect ratio** (width : height), taken from
the user-selected output sizes. All math stays in integers: box dimensions
are ``k * (aw, ah)`` for a positive integer ``k``, so the ratio is exact
and never drifts through rounding. Every move / resize keeps ``k`` integral
and clamps the box inside the image.

Conventions
-----------
* Coordinates are integers in image pixels; (x, y) is the top-left corner.
* ``aspect`` is a reduced integer pair ``(aw, ah)``, e.g. ``(1, 1)`` for a
  square, ``(1, 2)`` for a 100×200 output.
* Resize operations name the *anchor semantics* by which handle the user
  grabbed: dragging the bottom-right corner keeps the top-left fixed, etc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Handles: 4 corners + 4 edges, named like compass points on the box.
CORNERS = ("tl", "tr", "br", "bl")
EDGES = ("l", "t", "r", "b")


def reduce_aspect(w: int, h: int) -> tuple[int, int]:
    """Reduce (w, h) by their GCD -> canonical integer aspect ratio."""
    g = math.gcd(w, h)
    return w // g, h // g


def wrap_max_k(image_width: int, image_height: int,
               aspect: tuple[int, int]) -> int:
    """包裹模式的最大缩放因子：完全包裹图片的最小整数 k。

    即 box = k * (aw, ah) 是保持 ``aspect`` 且能包含整张图片的最小矩形
    （k >= 1）。普通模式的上限是图片内最大矩形，而这里允许在图片外部
    扩展。例如 1200×600 图片 + 1:1 → k=1200，box=1200×1200。
    """
    aw, ah = reduce_aspect(*aspect)
    return max(1, math.ceil(image_width / aw), math.ceil(image_height / ah))


@dataclass(frozen=True)
class CropState:
    """Immutable snapshot of the crop box (used by the undo stack)."""

    x: int
    y: int
    w: int
    h: int


class CropBoxModel:
    """Rectangular crop box with a fixed aspect, constrained to the image."""

    def __init__(self, image_width: int, image_height: int,
                 aspect: tuple[int, int] = (1, 1),
                 min_size: int = 16, wrap: bool = False) -> None:
        if image_width < 1 or image_height < 1:
            raise ValueError("image dimensions must be positive")
        aw, ah = reduce_aspect(*aspect)
        if aw < 1 or ah < 1:
            raise ValueError(f"invalid aspect: {aspect}")
        self._w_img = image_width
        self._h_img = image_height
        self._aw, self._ah = aw, ah
        #: 最小边长（自适应小图），用于推导最小缩放因子。
        self._min_dim = min(min_size, image_width, image_height)
        #: 包裹模式：裁切框允许越过图片边界，超出区域导出时填充背景。
        self._wrap = bool(wrap)
        self._x = 0
        self._y = 0
        self._k = 0
        self.reset()

    # ------------------------------------------------------------ properties
    @property
    def image_size(self) -> tuple[int, int]:
        return self._w_img, self._h_img

    @property
    def aspect(self) -> tuple[int, int]:
        return self._aw, self._ah

    @property
    def wrap(self) -> bool:
        return self._wrap

    @property
    def min_size(self) -> int:
        return self._min_dim

    @property
    def state(self) -> CropState:
        return CropState(self._x, self._y,
                         self._k * self._aw, self._k * self._ah)

    @property
    def box(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the current box."""
        return (self._x, self._y,
                self._k * self._aw, self._k * self._ah)

    # -------------------------------------------------------------- bounds
    def _min_k(self) -> int:
        """最小 k：尽量保证 w/h 都不小于 ``min_size``（图片过小时会放宽）。"""
        return max(1, math.ceil(self._min_dim / max(self._aw, self._ah)))

    def _max_k(self, room_w: int, room_h: int) -> int:
        """在 (room_w, room_h) 内可容纳的最大 k（至少 1）。"""
        return max(1, min(room_w // self._aw, room_h // self._ah))

    def _clamp_k(self, k: int, k_max: int) -> int:
        lo = min(self._min_k(), k_max)
        return max(lo, min(k, k_max))

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))

    # ------------------------------------------------------ wrap mode
    def _global_k_max(self) -> int:
        """当前模式允许的最大 k（包裹模式允许在图片外扩展）。"""
        if self._wrap:
            return wrap_max_k(self._w_img, self._h_img,
                              (self._aw, self._ah))
        return self._max_k(self._w_img, self._h_img)

    def _room_k_max(self, room_w: int, room_h: int) -> int:
        """拖拽缩放时的单次 k 上限。

        包裹模式只受全局包裹上限约束（允许越过图片边界）；普通模式
        受锚点与图片边界留下的房间限制。
        """
        if self._wrap:
            return self._global_k_max()
        return self._max_k(room_w, room_h)

    def _wrap_canvas(self) -> tuple[int, int, int, int]:
        """包裹画布：能完整包裹图片的最大框，居中于图片。

        即 ``wrap_fit`` 的结果（k = wrap_max_k）。UI 中图片外的灰色填充
        区就是画布范围，裁切框只能在画布内活动，因此移动/缩放都以画布
        为边界。
        """
        k = self._global_k_max()
        w, h = k * self._aw, k * self._ah
        return (round((self._w_img - w) / 2),
                round((self._h_img - h) / 2), w, h)

    def _x_bounds(self, w: int) -> tuple[int, int]:
        """x 的合法范围。

        包裹模式：框必须整体落在包裹画布（灰色区域）内，即
        x ∈ [canvas_x, canvas_x + canvas_w - w]，不越出画布边界；
        画布内可自由活动。普通模式严格钳制在图片内。
        """
        if self._wrap:
            cx, _cy, cw, _ch = self._wrap_canvas()
            return cx, cx + cw - w
        return 0, self._w_img - w

    def _y_bounds(self, h: int) -> tuple[int, int]:
        """y 的合法范围（见 _x_bounds）。"""
        if self._wrap:
            _cx, cy, _cw, ch = self._wrap_canvas()
            return cy, cy + ch - h
        return 0, self._h_img - h

    def _clamp_position(self) -> None:
        """把 x/y 钳制到当前模式的合法范围。"""
        w, h = self._k * self._aw, self._k * self._ah
        self._x = self._clamp(self._x, *self._x_bounds(w))
        self._y = self._clamp(self._y, *self._y_bounds(h))

    def _centered_position(self) -> tuple[int, int]:
        """使裁切框中心对齐图片中心时的 (x, y)。"""
        w, h = self._k * self._aw, self._k * self._ah
        return round((self._w_img - w) / 2), round((self._h_img - h) / 2)

    def set_wrap(self, wrap: bool) -> CropState:
        """切换包裹模式，并把当前几何钳制到新模式边界。

        开启时保持中心、允许越界（k 受包裹上限约束）；关闭时把越界
        部分缩回图片内。若要“开启 + 最大化 + 居中”一步到位，用
        :meth:`wrap_fit`。
        """
        if wrap == self._wrap:
            return self.state
        self._wrap = bool(wrap)
        cx = self._x + self._k * self._aw / 2
        cy = self._y + self._k * self._ah / 2
        self._k = self._clamp_k(self._k, self._global_k_max())
        nw, nh = self._k * self._aw, self._k * self._ah
        self._x = self._clamp(round(cx - nw / 2), *self._x_bounds(nw))
        self._y = self._clamp(round(cy - nh / 2), *self._y_bounds(nh))
        return self.state

    def wrap_fit(self) -> CropState:
        """包裹模式：裁切框设为能完全包裹图片的最大框，中心对齐图片。"""
        self._wrap = True
        self._k = self._global_k_max()
        self._x, self._y = self._centered_position()
        return self.state

    # ------------------------------------------------------------- mutation
    def reset(self) -> CropState:
        """默认框：满足比例的最大矩形。

        普通模式位于左上角；包裹模式下为能完全包裹图片的最大框并居中。
        """
        self._k = self._global_k_max()
        if self._wrap:
            self._x, self._y = self._centered_position()
        else:
            self._x, self._y = 0, 0
        return self.state

    def set_state(self, state: CropState) -> CropState:
        """应用一个状态；形状会被钳制到当前比例，位置被钳制在边界内。

        传入的状态比例与当前不同时，忽略其形状、保留其位置意图。
        """
        k = self._k
        if reduce_aspect(state.w, state.h) == (self._aw, self._ah):
            k = state.w // self._aw          # 同比例状态
        self._k = self._clamp_k(k, self._global_k_max())
        self._x = self._clamp(
            state.x, *self._x_bounds(self._k * self._aw))
        self._y = self._clamp(
            state.y, *self._y_bounds(self._k * self._ah))
        return self.state

    def set_aspect(self, aspect: tuple[int, int]) -> CropState:
        """切换宽高比：保持框中心尽量不动，缩放 k 以适配新比例。

        用于用户改选输出尺寸比例时，裁切框平滑地切换比例。
        """
        aw, ah = reduce_aspect(*aspect)
        if aw < 1 or ah < 1:
            raise ValueError(f"invalid aspect: {aspect}")
        if (aw, ah) == (self._aw, self._ah):
            return self.state
        cx = self._x + self._k * self._aw / 2
        cy = self._y + self._k * self._ah / 2
        self._aw, self._ah = aw, ah
        self._k = self._clamp_k(self._k, self._global_k_max())
        nw, nh = self._k * aw, self._k * ah
        self._x = self._clamp(round(cx - nw / 2), *self._x_bounds(nw))
        self._y = self._clamp(round(cy - nh / 2), *self._y_bounds(nh))
        return self.state

    def move_by(self, dx: int, dy: int) -> CropState:
        w, h = self._k * self._aw, self._k * self._ah
        self._x = self._clamp(self._x + dx, *self._x_bounds(w))
        self._y = self._clamp(self._y + dy, *self._y_bounds(h))
        return self.state

    # -------------------------------------------------------------- resize
    def _k_target(self, delta_w: int, delta_h: int) -> int:
        """由主导轴的像素增量推导目标 k（取整）。"""
        if abs(delta_w) >= abs(delta_h):
            return round((self._k * self._aw + delta_w) / self._aw)
        return round((self._k * self._ah + delta_h) / self._ah)

    def _apply_k(self, k: int, k_max: int) -> None:
        self._k = self._clamp_k(k, k_max)

    def resize_corner(self, corner: str, dx: int, dy: int) -> CropState:
        """Drag ``corner`` by (dx, dy); the opposite corner stays fixed.

        The box keeps its aspect ratio, following the dominant drag axis so
        diagonal movement feels natural.
        """
        if corner not in CORNERS:
            raise ValueError(f"unknown corner: {corner}")
        w, h = self._k * self._aw, self._k * self._ah
        if corner == "br":                       # anchor top-left
            k_max = self._room_k_max(self._w_img - self._x, self._h_img - self._y)
            self._apply_k(self._k_target(dx, dy), k_max)
        elif corner == "tl":                     # anchor bottom-right
            k_max = self._room_k_max(self._x + w, self._y + h)
            self._apply_k(self._k_target(-dx, -dy), k_max)
            self._x = self._x + w - self._k * self._aw
            self._y = self._y + h - self._k * self._ah
        elif corner == "tr":                     # anchor bottom-left
            k_max = self._room_k_max(self._w_img - self._x, self._y + h)
            self._apply_k(self._k_target(dx, -dy), k_max)
            self._y = self._y + h - self._k * self._ah
        else:  # "bl"                            # anchor top-right
            k_max = self._room_k_max(self._x + w, self._h_img - self._y)
            self._apply_k(self._k_target(-dx, dy), k_max)
            self._x = self._x + w - self._k * self._aw
        self._clamp_position()
        return self.state

    def resize_edge(self, edge: str, delta: int) -> CropState:
        """Drag ``edge`` outward by ``delta`` px; opposite edge stays fixed.

        ``delta > 0`` grows the box. The perpendicular dimension follows the
        aspect ratio automatically.
        """
        if edge not in EDGES:
            raise ValueError(f"unknown edge: {edge}")
        w, h = self._k * self._aw, self._k * self._ah
        if edge == "r":
            k_max = self._room_k_max(self._w_img - self._x, self._h_img - self._y)
            self._apply_k(round((w + delta) / self._aw), k_max)
        elif edge == "b":
            k_max = self._room_k_max(self._w_img - self._x, self._h_img - self._y)
            self._apply_k(round((h + delta) / self._ah), k_max)
        elif edge == "l":
            k_max = self._room_k_max(self._x + w, self._h_img - self._y)
            self._apply_k(round((w + delta) / self._aw), k_max)
            self._x = self._x + w - self._k * self._aw
        else:  # "t"
            k_max = self._room_k_max(self._w_img - self._x, self._y + h)
            self._apply_k(round((h + delta) / self._ah), k_max)
            self._y = self._y + h - self._k * self._ah
        self._clamp_position()
        return self.state

    def resize_centered(self, delta: int) -> CropState:
        """Grow/shrink around the box center (Shift+滚轮 / 居中缩放)。"""
        cx = self._x + self._k * self._aw / 2
        cy = self._y + self._k * self._ah / 2
        k = self._clamp_k(round((self._k * self._aw + delta) / self._aw),
                          self._global_k_max())
        self._k = k
        nw, nh = k * self._aw, k * self._ah
        self._x = self._clamp(round(cx - nw / 2), *self._x_bounds(nw))
        self._y = self._clamp(round(cy - nh / 2), *self._y_bounds(nh))
        return self.state
