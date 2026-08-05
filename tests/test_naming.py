"""Unit tests for core.naming (Qt-free filename template rendering)."""
from __future__ import annotations

from datetime import datetime

from core.naming import DEFAULT_TEMPLATE, render_filename


def test_default_template_square() -> None:
    out = render_filename(DEFAULT_TEMPLATE, name="logo", fmt="png",
                          size=(16, 16))
    assert out == "logo_16x16.png"


def test_default_template_non_square() -> None:
    out = render_filename(DEFAULT_TEMPLATE, name="logo", fmt="png",
                          size=(100, 200))
    assert out == "logo_100x200.png"


def test_all_placeholders_and_timestamp() -> None:
    when = datetime(2026, 8, 2, 15, 30, 45)
    template = "{format}_{size_}（{size}）_{name}_$yyyy-MM-dd_HH-mm-ss$.png"
    out = render_filename(template, name="logo", fmt="png", size=(800, 800),
                          when=when)
    assert out == "png_800_800（800x800）_logo_2026-08-02_15-30-45.png"


def test_w_h_placeholders() -> None:
    assert render_filename("{w}x{h}", name="x", fmt="png",
                           size=(300, 150)) == "300x150"


def test_size_underscore_variant() -> None:
    assert render_filename("{size_}", name="x", fmt="png",
                           size=(100, 200)) == "100_200"
    assert render_filename("{size_}", name="x", fmt="png",
                           size=(64, 64)) == "64_64"


def test_size_full_always_wide_times_height() -> None:
    assert render_filename("{size}", name="x", fmt="png",
                           size=(64, 64)) == "64x64"


def test_unknown_placeholders_left_untouched() -> None:
    out = render_filename("a_{zz}_b", name="x", fmt="png", size=(1, 1))
    assert out == "a_{zz}_b"
