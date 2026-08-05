"""Icon Crop Studio — application entry point.

Run with:  python main.py [--debug]
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QIcon

from app_info import APP_ICON, APP_NAME, APP_VERSION, ORG_NAME
from core.config_manager import ConfigManager
from core.localization import localization
from ui.theme import apply_theme
from utils.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    setup_logging(logging.DEBUG if "--debug" in args else logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("%s %s starting", APP_NAME, APP_VERSION)

    # Import Qt only after logging is ready so import errors get logged.
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(QIcon(str(APP_ICON)))

    config_manager = ConfigManager()
    config = config_manager.load()
    localization.set_language(config.language)
    apply_theme(app, config.theme)

    window = MainWindow(config_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
