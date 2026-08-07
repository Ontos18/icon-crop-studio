"""Crop + export to ICO / PNG / JPG (Qt-free, Pillow-based).

This module is pure Python so the entire export pipeline — the part users
actually care about — is fully unit-tested, including re-reading generated
ICO files to verify every requested frame size is present.

Output naming
-------------
ICO : one file containing ALL selected sizes ......... <stem>.ico
PNG : one file per selected size ..................... <stem>_16.png,
      <stem>_100x200.png, ...
JPG : one file per selected size ..................... <stem>_16.jpg, ...

``ExportSettings.sizes`` holds (width, height) pairs, so square and
non-square outputs (e.g. 800x800 or 100x200) are both supported; the crop
box keeps the same aspect ratio as the selected outputs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from core.naming import DEFAULT_TEMPLATE, render_filename
from models.crop_box import CropState

logger = logging.getLogger(__name__)

#: Formats the exporter understands (checkbox order in the UI).
EXPORT_FORMATS: tuple[str, ...] = ("ico", "png", "jpg")

_ICO_MAX_SIZE = 256          # Windows icon format's hard per-frame limit
_RESIZE_MAX_SIZE = 32768     # defensive limit against accidental huge output
_JPG_BACKGROUND = (255, 255, 255)   # alpha is flattened onto white

#: Alias kept for callers/tests that build size tuples.
Size = tuple[int, int]


@dataclass(frozen=True)
class ExportSettings:
    """Everything the exporter needs besides the image and the crop box."""

    formats: tuple[str, ...]
    sizes: tuple[tuple[int, int], ...]   # (width, height) per output
    output_dir: Path
    overwrite: bool = True
    jpg_quality: int = 92
    template: str = DEFAULT_TEMPLATE     # 文件名模板，见 core.naming
    brightness: int = 0                  # -100（暗）~ 100（亮），0 = 原图
    wrap: bool = False                   # 包裹模式：越界区域填充背景（PNG 透明/JPG 白）
    processing_mode: str = "crop"        # "crop" / "resize"
    resize_axis: str = "width"           # resize 模式固定 width / height
    resize_value: int = 256               # resize 模式目标边长（像素）


@dataclass
class ExportResult:
    """Outcome of one export job (also carried across the Qt thread hop)."""

    source: Path
    outputs: list[Path] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def validate_settings(settings: ExportSettings) -> str | None:
    """Return an i18n message key describing the first problem, or None."""
    # Path("") stringifies to "." — treat both as "not set".
    if str(settings.output_dir).strip() in ("", "."):
        return "msg.no_output_dir"
    if not settings.formats:
        return "msg.no_formats"
    if settings.processing_mode not in ("crop", "resize"):
        return "msg.invalid_processing_mode"
    if settings.processing_mode == "crop" and not settings.sizes:
        return "msg.no_sizes"
    if settings.processing_mode == "resize":
        if settings.resize_axis not in ("width", "height"):
            return "msg.resize_invalid"
        if settings.resize_value < 1:
            return "msg.resize_invalid"
        if settings.resize_value > _RESIZE_MAX_SIZE:
            return "msg.resize_too_large"
    unknown = set(settings.formats) - set(EXPORT_FORMATS)
    if unknown:
        return "msg.no_formats"
    if settings.processing_mode == "crop" and any(
            w < 1 or h < 1 for w, h in settings.sizes):
        return "msg.no_sizes"
    # ICO frames are limited to 256px by the Windows icon spec.
    if (settings.processing_mode == "crop" and "ico" in settings.formats
            and any(w > _ICO_MAX_SIZE or h > _ICO_MAX_SIZE
                    for w, h in settings.sizes)):
        return "msg.ico_too_large"
    return None


def export_crop(source: Path, crop: CropState,
                settings: ExportSettings) -> ExportResult:
    """Crop ``source`` at ``crop`` and write all requested outputs.

    Never raises: any failure is reported in ``ExportResult.error`` so the
    GUI thread can flag the image red without crashing the worker pool.
    """
    result = ExportResult(source=source)
    problem = validate_settings(settings)
    if problem is not None:
        result.error = problem
        return result

    try:
        image = _open_rgba(source)
    except (OSError, ValueError) as exc:
        logger.error("Cannot open %s: %s", source, exc)
        result.error = str(exc)
        return result

    if settings.processing_mode == "resize":
        cropped = _apply_brightness(image, settings.brightness)
        sizes = [proportional_size(
            image.width, image.height,
            settings.resize_axis, settings.resize_value)]
        if any(w > _RESIZE_MAX_SIZE or h > _RESIZE_MAX_SIZE for w, h in sizes):
            result.error = "msg.resize_too_large"
            return result
        if ("ico" in settings.formats
                and any(w > _ICO_MAX_SIZE or h > _ICO_MAX_SIZE
                        for w, h in sizes)):
            result.error = "msg.ico_too_large"
            return result
    else:
        cropped = _apply_brightness(
            _crop_with_padding(image, crop, settings.wrap), settings.brightness)
        sizes = _dedup_sizes(settings.sizes)
    try:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        if "ico" in settings.formats:
            result.outputs.append(_write_ico(cropped, source, settings, sizes))
        if "png" in settings.formats:
            result.outputs.extend(_write_per_size(
                cropped, source, settings, sizes, "png"))
        if "jpg" in settings.formats:
            result.outputs.extend(_write_per_size(
                cropped, source, settings, sizes, "jpg"))
    except OSError as exc:
        logger.error("Export failed for %s: %s", source, exc)
        result.error = str(exc)
        return result

    logger.info("Exported %s -> %d file(s)", source.name, len(result.outputs))
    return result


def crop_to_preview(source: Path, crop: CropState,
                    max_size: int = 256, brightness: int = 0,
                    wrap: bool = False) -> Image.Image:
    """Crop ``source`` at ``crop`` and scale to fit ``max_size`` px (RGBA).

    Feeds the live-preview widget. Uses the exact same open + crop +
    brightness path as :func:`export_crop` (including wrap-mode padding),
    so the preview always matches the export. The aspect ratio of the crop
    is preserved; small crops are upscaled so detail is visible.
    """
    cropped = _crop_with_padding(_open_rgba(source), crop, wrap)
    return _scaled_to_fit(_apply_brightness(cropped, brightness), max_size)


def image_to_preview(source: Path, max_size: int = 256,
                     brightness: int = 0) -> Image.Image:
    """Return a full-image preview for proportional-resize mode."""
    return _scaled_to_fit(
        _apply_brightness(_open_rgba(source), brightness), max_size)


def proportional_size(width: int, height: int, axis: str,
                      value: int) -> Size:
    """Calculate an aspect-preserving size with one requested edge fixed."""
    if width < 1 or height < 1 or value < 1 or axis not in ("width", "height"):
        raise ValueError("invalid proportional resize arguments")
    if axis == "width":
        return value, max(1, round(height * value / width))
    return max(1, round(width * value / height)), value


# --------------------------------------------------------------- internals
def _open_rgba(source: Path) -> Image.Image:
    """Open, EXIF-rotate and RGBA-convert ``source``.

    Raises ``OSError``/``ValueError`` on unreadable/corrupt files; callers
    decide how to surface the failure (export error vs. preview skip).
    """
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)   # match on-screen view
        return image.convert("RGBA")


def _clamped_crop(image: Image.Image, crop: CropState) -> Image.Image:
    """Crop with defensive clamping (a stale crop from another image must not
    produce a corrupt export)."""
    x = max(0, min(crop.x, image.width - 1))
    y = max(0, min(crop.y, image.height - 1))
    w = max(1, min(crop.w, image.width - x))
    h = max(1, min(crop.h, image.height - y))
    return image.crop((x, y, x + w, y + h))


def _crop_with_padding(image: Image.Image, crop: CropState,
                       wrap: bool) -> Image.Image:
    """Crop ``image`` at ``crop``, honouring the wrap-mode fill semantics.

    普通模式（wrap=False）：把越界部分钳制到图片内（防御性，行为不变）。
    包裹模式（wrap=True）：保留完整的 (w, h) 画布，图片外的区域填充透明
    （alpha=0；JPG 导出时由 ``_write_per_size`` 平坦成白色），原图内容
    按 crop 偏移放置 —— 预览与导出共用此路径，保证所见即所得。
    """
    if not wrap:
        return _clamped_crop(image, crop)
    x, y, w, h = crop.x, crop.y, crop.w, crop.h
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ix0, iy0 = max(0, x), max(0, y)
    ix1, iy1 = min(image.width, x + w), min(image.height, y + h)
    if ix1 > ix0 and iy1 > iy0:
        region = image.crop((ix0, iy0, ix1, iy1))
        canvas.paste(region, (ix0 - x, iy0 - y))
    return canvas


def _apply_brightness(image: Image.Image, brightness: int) -> Image.Image:
    """模拟画面显示的亮度效果（半透明白/黑叠加），保证所见即所得。

    显示层 ``_BrightnessEffect`` 用纯色叠加模拟亮度：
        变暗 value<0：黑色叠加，result = src * (1 - |value|/100)
        变亮 value>0：白色叠加，result = src*(1-v) + 255*v, v=value/100
    这里用同一套算法处理导出像素，使导出与画面显示完全一致
    （alpha 通道保持不变）。
    """
    if brightness == 0:
        return image
    value = max(-100, min(100, int(brightness)))
    if value < 0:
        # 黑色叠加 == 乘法压暗；ImageEnhance 只改 RGB，alpha 保持。
        return ImageEnhance.Brightness(image).enhance(1 - abs(value) / 100.0)
    # 变亮：往白色靠拢（与显示层白色叠加一致）。
    v = value / 100.0
    r, g, b, a = image.split()
    r = r.point(lambda p: round(p * (1 - v) + 255 * v))
    g = g.point(lambda p: round(p * (1 - v) + 255 * v))
    b = b.point(lambda p: round(p * (1 - v) + 255 * v))
    return Image.merge("RGBA", (r, g, b, a))


def _dedup_sizes(sizes: tuple[Size, ...]) -> list[Size]:
    """Remove duplicates while preserving order."""
    seen: set[Size] = set()
    out: list[Size] = []
    for size in sizes:
        if size not in seen:
            seen.add(size)
            out.append(size)
    return out


def _scaled(cropped: Image.Image, w: int, h: int) -> Image.Image:
    """Resize to exactly (w, h) with LANCZOS.

    The crop already has the requested aspect ratio, so this never distorts.
    """
    return cropped.resize((w, h), Image.Resampling.LANCZOS)


def _scaled_to_fit(cropped: Image.Image, max_size: int) -> Image.Image:
    """Scale preserving aspect so the longer side is ≤ ``max_size``."""
    scale = max_size / max(cropped.size)
    nw = max(1, round(cropped.width * scale))
    nh = max(1, round(cropped.height * scale))
    return cropped.resize((nw, nh), Image.Resampling.LANCZOS)


def _output_name(source: Path, settings: ExportSettings,
                 fmt: str, size: Size) -> str:
    """Render the output file name from the user's template."""
    return render_filename(
        settings.template, name=source.stem, fmt=fmt, size=size)


def _target_path(settings: ExportSettings, name: str) -> Path:
    """Resolve the output path, uniquifying when overwrite is disabled."""
    path = settings.output_dir / name
    if settings.overwrite or not path.exists():
        return path
    counter = 1
    while True:
        candidate = settings.output_dir / (
            f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _write_ico(cropped: Image.Image, source: Path,
               settings: ExportSettings, sizes: list[Size]) -> Path:
    """One .ico containing a frame for every selected size (≤256px).

    Pillow only writes ``append_images`` when the *first* image is the
    largest frame, so we order frames by size descending and make the
    biggest one the anchor image.
    """
    ordered = sorted(sizes, key=lambda s: max(s), reverse=True)
    frames = [_scaled(cropped, w, h) for w, h in ordered]
    name = _output_name(source, settings, "ico", sizes[0])
    path = _target_path(settings, name)
    frames[0].save(path, format="ICO",
                   sizes=[(w, h) for w, h in ordered],
                   append_images=frames[1:])
    return path


def _write_per_size(cropped: Image.Image, source: Path,
                    settings: ExportSettings, sizes: list[Size],
                    fmt: str) -> list[Path]:
    """One file per selected size, named from the user's template."""
    written: list[Path] = []
    for size in sizes:
        w, h = size
        frame = _scaled(cropped, w, h)
        path = _target_path(settings, _output_name(source, settings, fmt, size))
        if fmt == "jpg":
            background = Image.new("RGB", frame.size, _JPG_BACKGROUND)
            background.paste(frame, mask=frame.getchannel("A"))
            background.save(path, format="JPEG",
                            quality=settings.jpg_quality)
        else:
            frame.save(path, format="PNG")
        written.append(path)
    return written
