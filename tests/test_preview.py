"""Tests for core.exporter.crop_to_preview (Qt-free)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.exporter import ExportSettings, crop_to_preview, export_crop
from models.crop_box import CropState


def _make_source(tmp_path: Path, size: tuple[int, int] = (100, 80)) -> Path:
    """Red image with a green square at (10,10)-(40,40) to verify cropping."""
    image = Image.new("RGBA", size, (255, 0, 0, 255))
    for x in range(10, 40):
        for y in range(10, 40):
            image.putpixel((x, y), (0, 255, 0, 255))
    path = tmp_path / "src.png"
    image.save(path)
    return path


def test_preview_is_square_rgba(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    image = crop_to_preview(source, CropState(0, 0, 80, 80), max_size=64)
    assert image.size == (64, 64)
    assert image.mode == "RGBA"


def test_preview_upscales_small_crop(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    image = crop_to_preview(source, CropState(0, 0, 30, 30), max_size=256)
    assert image.size == (256, 256)


def test_preview_clamps_out_of_bounds_crop(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    image = crop_to_preview(source, CropState(90, 70, 500, 500), max_size=32)
    assert image.size == (32, 32)


def test_preview_matches_export_region(tmp_path: Path) -> None:
    """预览与导出的裁切区域一致（绿方块中心在两者中都应为绿色）。"""
    source = _make_source(tmp_path)
    crop = CropState(10, 10, 30, 30)
    preview = crop_to_preview(source, crop, max_size=30)
    r, g, b, a = preview.getpixel((15, 15))
    assert g > 200 and r < 50

    result = export_crop(source, crop,
                         ExportSettings(formats=("png",),
                                        sizes=((30, 30),),
                                        output_dir=tmp_path / "out"))
    assert result.ok
    with Image.open(result.outputs[0]) as img:
        r2, g2, b2, a2 = img.getpixel((15, 15))
    assert (r2, g2, b2, a2) == (r, g, b, a)


def test_preview_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises((OSError, ValueError)):
        crop_to_preview(tmp_path / "nope.png", CropState(0, 0, 16, 16))
