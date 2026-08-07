"""Persistent application configuration.

Design notes
------------
* ``AppConfig`` is a plain dataclass -> type-safe access everywhere
  (``config.thumbnail_page_size``) instead of stringly-typed dict lookups.
* Unknown keys in the JSON file are ignored, missing keys fall back to the
  dataclass defaults -> old config files keep working after upgrades.
* ``ConfigManager`` is deliberately Qt-free so it can be unit-tested and
  reused from CLI tools.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app_info import default_config_path

logger = logging.getLogger(__name__)

#: 预设的方形输出尺寸（默认尺寸条目，用户可删除）。
_DEFAULT_ENTRIES: list[list[int]] = [
    [16, 16], [24, 24], [32, 32], [48, 48],
    [64, 64], [128, 128], [256, 256],
]

#: 预设尺寸的公开只读引用（GUI 层用于区分"预设/自定义"）。
DEFAULT_SIZE_ENTRIES: list[list[int]] = _DEFAULT_ENTRIES


def _migrate_config(raw: dict[str, Any]) -> None:
    """把旧版尺寸配置（ico_sizes/custom_sizes/...）迁移到统一结构。

    幂等：新配置已含 ``size_entries`` 时不做任何事。
    """
    if "size_entries" in raw:
        return
    preset = [list(s) for s in _DEFAULT_ENTRIES]
    custom = [list(map(int, s)) for s in raw.get("custom_sizes", [])]
    raw["size_entries"] = preset + custom
    selected = [[s, s] for s in raw.get("ico_sizes", [16, 32, 48, 64, 128, 256])]
    selected += [list(map(int, s)) for s in raw.get("selected_custom_sizes", [])]
    raw["selected_sizes"] = selected
    for key in ("ico_sizes", "custom_sizes", "selected_custom_sizes"):
        raw.pop(key, None)


@dataclass
class AppConfig:
    """All user-tunable settings with their defaults."""

    # --- paths -----------------------------------------------------------
    input_dir: str = ""
    output_dir: str = ""

    # --- export ----------------------------------------------------------
    export_formats: list[str] = field(default_factory=lambda: ["ico"])
    #: 所有输出尺寸条目 [[w, h], ...]，用户可添加/删除（含预设方形与自定义）。
    size_entries: list[list[int]] = field(default_factory=lambda: [
        [16, 16], [24, 24], [32, 32], [48, 48],
        [64, 64], [128, 128], [256, 256]])
    #: 当前勾选的尺寸（必须同比例，由 UI 保证）。
    selected_sizes: list[list[int]] = field(default_factory=lambda: [
        [16, 16], [32, 32], [48, 48], [64, 64], [128, 128], [256, 256]])
    auto_next_after_export: bool = True
    overwrite_existing: bool = True
    #: 导出文件名模板，见 core.naming（默认 {name}_{size}.{format}）。
    filename_template: str = "{name}_{size}.{format}"
    #: 图片处理方式："crop" 裁切，"resize" 保留完整图片并等比缩放。
    processing_mode: str = "crop"
    #: 等比缩放时固定的边："width" 或 "height"。
    resize_axis: str = "width"
    #: 等比缩放时目标边长（像素）。
    resize_value: int = 256

    # --- UI --------------------------------------------------------------
    language: str = "zh_CN"
    theme: str = "system"
    thumbnail_size: int = 96
    thumbnail_page_size: int = 20

    # --- behaviour -------------------------------------------------------
    folder_watch_enabled: bool = False
    remember_crop_between_images: bool = True
    #: 包裹模式：裁切框允许越过图片边界，超出区域导出时填充背景（透明/白）。
    wrap_mode: bool = False
    #: WASD 裁切框每步移动的像素数（无修饰键时）。
    crop_move_speed: int = 10
    #: Shift+滚轮缩放裁切框的每格步长（像素）。
    wheel_resize_step: int = 100
    #: Ctrl+滚轮缩放画布的每格倍率（>1，如 1.25 表示放大 1.25 倍）。
    wheel_zoom_step: float = 1.25
    #: 最后一个裁切框的归一化相对位置 "nx,ny,nw,nh"（0~1），用于跨会话恢复；
    #: 空字符串表示无记录（首次打开 → 默认左上角）。
    last_crop_relative: str = ""

    # --- shortcuts: action id -> QKeySequence portable string -------------
    shortcuts: dict[str, str] = field(default_factory=dict)

    # --- window geometry (restored on start) ------------------------------
    window_geometry: str = ""  # base64 QByteArray, empty = default


class ConfigManager:
    """Loads, holds and saves the single :class:`AppConfig` instance."""

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path if path is not None else default_config_path()
        self._config: AppConfig = AppConfig()

    # ------------------------------------------------------------------ API
    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        """Read the JSON file; on any error fall back to defaults."""
        if not self._path.is_file():
            logger.info("No config file at %s, using defaults", self._path)
            self._config = AppConfig()
            return self._config
        try:
            raw: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
            _migrate_config(raw)
            valid_names = {f.name for f in dataclasses.fields(AppConfig)}
            known = {k: v for k, v in raw.items() if k in valid_names}
            self._config = AppConfig(**known)
            logger.info("Config loaded from %s", self._path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to load config (%s), using defaults", exc)
            self._config = AppConfig()
        return self._config

    def save(self) -> bool:
        """Write the current config atomically. Returns True on success."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(dataclasses.asdict(self._config),
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
            logger.debug("Config saved to %s", self._path)
            return True
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)
            return False

    def reset_to_defaults(self) -> AppConfig:
        """Restore factory defaults (does not save automatically)."""
        self._config = AppConfig()
        return self._config

    def replace(self, config: AppConfig) -> None:
        """Swap in a whole new config (settings dialog edits a copy)."""
        self._config = config
