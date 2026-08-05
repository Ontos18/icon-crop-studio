"""Central logging configuration (console + rotating file)."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app_info import default_log_dir

_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO,
                  log_dir: Path | None = None) -> None:
    """Configure the root logger once, at application start.

    * Console handler: ``level`` (INFO by default, DEBUG with ``--debug``).
    * File handler: always DEBUG, rotating 5 x 2 MB in the user log dir,
      so users can send logs when reporting problems.
    """
    root = logging.getLogger()
    if root.handlers:                       # already configured (tests)
        return
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    directory = log_dir if log_dir is not None else default_log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            directory / "icon_crop_studio.log",
            maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(file_handler)
    except OSError as exc:                  # never crash because of logging
        root.warning("File logging disabled: %s", exc)
