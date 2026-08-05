"""Application-wide constants.

Pure-Python module: must NOT import Qt so that it is importable from
tests and from non-GUI tools (e.g. CLI batch export in the future).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME: str = "Icon Crop Studio"
APP_ID: str = "IconCropStudio"          # used for config / log folder names
APP_VERSION: str = "0.7.0"              # Phases 5/7/8/9/10/11/12 complete
ORG_NAME: str = "IconCropStudio"

#: 应用图标（仓库根目录的 ICO 文件，256×256）。
APP_ICON: Path = Path(__file__).resolve().parent / "icon.ico"

#: Image file extensions the application can load (lower-case, with dot).
SUPPORTED_INPUT_EXTENSIONS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif", ".ico",
)

#: ICO sizes offered in the export panel.
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)


def user_data_dir() -> Path:
    """Return the per-user writable directory for config / logs / cache.

    Windows:  %APPDATA%/IconCropStudio
    Other OS: ~/.config/icon_crop_studio   (useful for development/tests)
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / APP_ID
    return Path.home() / ".config" / "icon_crop_studio"


def default_config_path() -> Path:
    """Path of the persistent JSON configuration file."""
    return user_data_dir() / "config.json"


def default_log_dir() -> Path:
    """Directory where rotating log files are written."""
    return user_data_dir() / "logs"
