"""Tests for core.exporter — generates REAL files and reads them back."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.exporter import (
    ExportSettings, crop_to_preview, export_crop, proportional_size,
    validate_settings,
)
from models.crop_box import CropBoxModel, CropState


def _make_source(tmp_path: Path, size: tuple[int, int] = (100, 80),
                 name: str = "sample.png") -> Path:
    """Red image with a green square at (10,10)-(40,40) to verify cropping."""
    image = Image.new("RGBA", size, (255, 0, 0, 255))
    for x in range(10, 40):
        for y in range(10, 40):
            image.putpixel((x, y), (0, 255, 0, 255))
    path = tmp_path / name
    image.save(path)
    return path


def _settings(tmp_path: Path, **kwargs) -> ExportSettings:
    defaults = dict(formats=("ico",), sizes=((16, 16), (32, 32)),
                    output_dir=tmp_path / "out", overwrite=True)
    defaults.update(kwargs)
    return ExportSettings(**defaults)


def test_ico_contains_all_requested_sizes(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(0, 0, 80, 80),
                         _settings(tmp_path, sizes=((16, 16), (32, 32), (48, 48), (256, 256))))
    assert result.ok, result.error
    ico_path = result.outputs[0]
    assert ico_path.suffix == ".ico"
    with Image.open(ico_path) as ico:
        available = ico.info.get("sizes") or set()
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(available)


def test_png_one_file_per_size_with_correct_dimensions(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(0, 0, 80, 80),
                         _settings(tmp_path, formats=("png",), sizes=((16, 16), (64, 64))))
    assert result.ok
    names = sorted(p.name for p in result.outputs)
    assert names == ["sample_16x16.png", "sample_64x64.png"]
    for path in result.outputs:
        with Image.open(path) as img:
            w, h = (int(x) for x in path.stem.rsplit("_", 1)[1].split("x"))
            assert img.size == (w, h)


def test_jpg_flattens_alpha_to_rgb(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(0, 0, 80, 80),
                         _settings(tmp_path, formats=("jpg",), sizes=((32, 32),)))
    assert result.ok
    with Image.open(result.outputs[0]) as img:
        assert img.mode == "RGB"
        assert img.size == (32, 32)


def test_crop_region_is_respected(tmp_path: Path) -> None:
    """Crop exactly the green square -> exported pixels must be green."""
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(10, 10, 30, 30),
                         _settings(tmp_path, formats=("png",), sizes=((30, 30),)))
    assert result.ok
    with Image.open(result.outputs[0]) as img:
        r, g, b, a = img.getpixel((15, 15))
    assert g > 200 and r < 50


def test_png_non_square_output(tmp_path: Path) -> None:
    source = _make_source(tmp_path)   # 100x80
    result = export_crop(source, CropState(0, 0, 40, 80),
                         _settings(tmp_path, formats=("png",),
                                   sizes=((100, 200),)))
    assert result.ok
    assert result.outputs[0].name == "sample_100x200.png"
    with Image.open(result.outputs[0]) as img:
        assert img.size == (100, 200)


def test_ico_contains_non_square_frames(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(0, 0, 40, 80),
                         _settings(tmp_path, formats=("ico",),
                                   sizes=((32, 64), (16, 16))))
    assert result.ok
    with Image.open(result.outputs[0]) as ico:
        available = set(ico.info.get("sizes") or ())
    assert (32, 64) in available and (16, 16) in available


def test_all_three_formats_together(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = export_crop(source, CropState(0, 0, 80, 80),
                         _settings(tmp_path, formats=("ico", "png", "jpg"),
                                   sizes=((16, 16), (32, 32))))
    assert result.ok
    suffixes = sorted(p.suffix for p in result.outputs)
    assert suffixes == [".ico", ".jpg", ".jpg", ".png", ".png"]


def test_no_overwrite_uniquifies_names(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    settings = _settings(tmp_path, formats=("ico",), sizes=((16, 16),),
                         overwrite=False)
    first = export_crop(source, CropState(0, 0, 80, 80), settings)
    second = export_crop(source, CropState(0, 0, 80, 80), settings)
    assert first.ok and second.ok
    assert first.outputs[0].name == "sample_16x16.ico"
    assert second.outputs[0].name == "sample_16x16 (1).ico"


def test_overwrite_reuses_name(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    settings = _settings(tmp_path, formats=("ico",), sizes=((16, 16),))
    export_crop(source, CropState(0, 0, 80, 80), settings)
    result = export_crop(source, CropState(0, 0, 80, 80), settings)
    assert result.outputs[0].name == "sample_16x16.ico"


def test_out_of_bounds_crop_is_clamped_not_fatal(tmp_path: Path) -> None:
    source = _make_source(tmp_path)   # 100x80
    result = export_crop(source, CropState(90, 70, 500, 500),
                         _settings(tmp_path, formats=("png",), sizes=((16, 16),)))
    assert result.ok


def test_unreadable_source_reports_error(tmp_path: Path) -> None:
    bogus = tmp_path / "broken.png"
    bogus.write_bytes(b"this is not an image")
    result = export_crop(bogus, CropState(0, 0, 10, 10), _settings(tmp_path))
    assert not result.ok
    assert result.outputs == []


def test_validate_settings_message_keys(tmp_path: Path) -> None:
    ok = _settings(tmp_path)
    assert validate_settings(ok) is None
    assert validate_settings(
        _settings(tmp_path, output_dir=Path(""))) == "msg.no_output_dir"
    assert validate_settings(
        _settings(tmp_path, formats=())) == "msg.no_formats"
    assert validate_settings(
        _settings(tmp_path, sizes=())) == "msg.no_sizes"
    # ICO 帧超 256px 触发专门提示（PNG/JPG 不受限）
    assert validate_settings(
        _settings(tmp_path, sizes=((512, 512),))) == "msg.ico_too_large"
    assert validate_settings(
        _settings(tmp_path, formats=("png",),
                  sizes=((512, 512),))) is None
    assert validate_settings(
        _settings(tmp_path, formats=("bmp",))) == "msg.no_formats"


def test_gif_first_frame_used(tmp_path: Path) -> None:
    frames = [Image.new("RGB", (50, 50), c) for c in ("blue", "red")]
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:])
    result = export_crop(gif, CropState(0, 0, 50, 50),
                         _settings(tmp_path, formats=("png",), sizes=((16, 16),)))
    assert result.ok
    with Image.open(result.outputs[0]) as img:
        r, g, b, a = img.convert("RGBA").getpixel((8, 8))
    assert b > 200 and r < 50          # first (blue) frame, not the red one


# ------------------------------------------------------------- 包裹模式导出
def _wrap_fit(size: tuple[int, int]) -> CropState:
    """包裹模式的最大框：恰好包含整张原图并居中（Web 800x800 场景）。"""
    m = CropBoxModel(*size, aspect=(1, 1), wrap=True)
    return m.wrap_fit()


def test_wrap_png_horizontal_fills_alpha(tmp_path: Path) -> None:
    """横向长图 1200x600：wrap 导出 PNG，上下越界区透明，中心为原图内容。"""
    source = _make_source(tmp_path, size=(1200, 600))
    crop = _wrap_fit((1200, 600))
    assert crop == CropState(0, -300, 1200, 1200)   # 上下各扩展 300px
    result = export_crop(source, crop,
                         _settings(tmp_path, formats=("png",),
                                   sizes=((800, 800),), wrap=True))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as img:
        assert img.size == (800, 800)
        top = img.convert("RGBA").getpixel((400, 20))      # 顶部填充
        bottom = img.convert("RGBA").getpixel((400, 780))  # 底部填充
        center = img.convert("RGBA").getpixel((400, 400))  # 图片内容
    assert top[3] == 0 and bottom[3] == 0                 # 透明 alpha
    assert center[3] == 255 and center[0] > 200 and center[1] < 50


def test_wrap_png_vertical_fills_alpha(tmp_path: Path) -> None:
    """纵向长图 600x1200：wrap 导出 PNG，左右越界区透明。"""
    source = _make_source(tmp_path, size=(600, 1200))
    crop = _wrap_fit((600, 1200))
    assert crop == CropState(-300, 0, 1200, 1200)   # 左右各扩展 300px
    result = export_crop(source, crop,
                         _settings(tmp_path, formats=("png",),
                                   sizes=((800, 800),), wrap=True))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as img:
        assert img.size == (800, 800)
        left = img.convert("RGBA").getpixel((20, 400))      # 左侧填充
        right = img.convert("RGBA").getpixel((780, 400))    # 右侧填充
        center = img.convert("RGBA").getpixel((400, 400))
    assert left[3] == 0 and right[3] == 0
    assert center[3] == 255 and center[0] > 200


def test_wrap_jpg_fills_white(tmp_path: Path) -> None:
    """横向长图 wrap 导出 JPG：越界区平坦为纯白，内容区仍为原图颜色。"""
    source = _make_source(tmp_path, size=(1200, 600))
    crop = _wrap_fit((1200, 600))
    result = export_crop(source, crop,
                         _settings(tmp_path, formats=("jpg",),
                                   sizes=((800, 800),), wrap=True))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as img:
        assert img.mode == "RGB"
        assert img.size == (800, 800)
        top = img.getpixel((400, 20))        # 顶部填充（JPEG 有损，取近白）
        center = img.getpixel((400, 400))    # 内容区
    assert top[0] >= 245 and top[1] >= 245 and top[2] >= 245
    assert center[0] > 200 and center[1] < 80 and center[2] < 80


def test_normal_mode_unaffected_by_wrap_fill(tmp_path: Path) -> None:
    """普通模式回归：wrap=False 时越界被 clamp，导出无透明填充、尺寸正确。"""
    source = _make_source(tmp_path, size=(1200, 600))
    # 传入越界裁切（普通模式下会被钳制回图片内，行为与旧版一致）。
    result = export_crop(source, CropState(0, -300, 1200, 1200),
                         _settings(tmp_path, formats=("png",),
                                   sizes=((800, 400),), wrap=False))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as img:
        assert img.size == (800, 400)
        px = img.convert("RGBA").getpixel((400, 200))
    assert px[3] == 255 and px[0] > 200      # 全图有内容，无透明填充


def test_wrap_preview_matches_export_pixels(tmp_path: Path) -> None:
    """所见即所得：wrap 模式下预览（crop_to_preview）与导出像素完全一致。"""
    source = _make_source(tmp_path, size=(1200, 600))
    crop = _wrap_fit((1200, 600))
    result = export_crop(source, crop,
                         _settings(tmp_path, formats=("png",),
                                   sizes=((800, 800),), wrap=True))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as img:
        exported = img.convert("RGBA")
    preview = crop_to_preview(source, crop, max_size=800, wrap=True)
    assert preview.size == (800, 800)
    assert list(preview.tobytes()) == list(exported.tobytes())


# ---------------------------------------------------------- 等比缩放模式
def test_proportional_size_by_width_and_height() -> None:
    assert proportional_size(1600, 800, "width", 400) == (400, 200)
    assert proportional_size(1600, 800, "height", 400) == (800, 400)
    assert proportional_size(3, 2, "width", 10) == (10, 7)


def test_resize_mode_exports_full_image_by_width(tmp_path: Path) -> None:
    source = _make_source(tmp_path, size=(100, 80))
    # Crop deliberately points at only the green area; resize mode must ignore it.
    result = export_crop(
        source, CropState(10, 10, 30, 30),
        _settings(tmp_path, formats=("png",), sizes=(),
                  processing_mode="resize", resize_axis="width",
                  resize_value=50))
    assert result.ok, result.error
    assert result.outputs[0].name == "sample_50x40.png"
    with Image.open(result.outputs[0]) as image:
        assert image.size == (50, 40)
        # Top-left is red in the full source, proving it was not crop-only output.
        r, g, b, a = image.convert("RGBA").getpixel((1, 1))
    assert r > 200 and g < 50 and b < 50 and a == 255


def test_resize_mode_exports_by_height(tmp_path: Path) -> None:
    source = _make_source(tmp_path, size=(160, 80))
    result = export_crop(
        source, CropState(0, 0, 1, 1),
        _settings(tmp_path, formats=("jpg",), sizes=(),
                  processing_mode="resize", resize_axis="height",
                  resize_value=100))
    assert result.ok, result.error
    with Image.open(result.outputs[0]) as image:
        assert image.size == (200, 100)


def test_resize_mode_validates_without_crop_sizes(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path, formats=("png",), sizes=(), processing_mode="resize",
        resize_axis="width", resize_value=400)
    assert validate_settings(settings) is None
    assert validate_settings(_settings(
        tmp_path, sizes=(), processing_mode="resize",
        resize_axis="diagonal")) == "msg.resize_invalid"


def test_resize_mode_ico_checks_computed_other_edge(tmp_path: Path) -> None:
    source = _make_source(tmp_path, size=(100, 200))
    result = export_crop(
        source, CropState(0, 0, 1, 1),
        _settings(tmp_path, sizes=(), processing_mode="resize",
                  resize_axis="width", resize_value=200))
    assert not result.ok
    assert result.error == "msg.ico_too_large"


def test_resize_mode_rejects_extreme_computed_dimension(tmp_path: Path) -> None:
    source = tmp_path / "extreme.png"
    Image.new("RGBA", (1, 100), (255, 0, 0, 255)).save(source)
    result = export_crop(
        source, CropState(0, 0, 1, 1),
        _settings(tmp_path, formats=("png",), sizes=(),
                  processing_mode="resize", resize_axis="width",
                  resize_value=1000))
    assert not result.ok
    assert result.error == "msg.resize_too_large"
