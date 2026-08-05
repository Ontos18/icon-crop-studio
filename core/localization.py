"""Runtime i18n with JSON catalogs.

Why not Qt Linguist (.ts/.qm)?
------------------------------
* JSON catalogs need no lupdate/lrelease build step, are diff-friendly and
  trivially editable by translators.
* Adding a language = dropping one file into resources/i18n/.
* This module stays Qt-free (plain callback list instead of Signals) so the
  whole i18n layer is unit-testable without a QApplication.

Usage
-----
    from core.localization import tr, localization
    label.setText(tr("menu.file"))
    localization.set_language("en_US")          # fires all subscribers

Every widget registers a ``retranslate_ui`` callback so language switching
works live, without restarting the application.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: Language code -> native display name (shown in the language menu).
AVAILABLE_LANGUAGES: dict[str, str] = {
    "zh_CN": "简体中文",
    "en_US": "English",
}

DEFAULT_LANGUAGE: str = "zh_CN"
FALLBACK_LANGUAGE: str = "en_US"

_I18N_DIR: Path = Path(__file__).resolve().parent.parent / "resources" / "i18n"


class LocalizationManager:
    """Holds the active catalog and notifies subscribers on switch."""

    def __init__(self, i18n_dir: Path = _I18N_DIR) -> None:
        self._i18n_dir = i18n_dir
        self._language: str = DEFAULT_LANGUAGE
        self._catalog: dict[str, str] = {}
        self._fallback: dict[str, str] = self._load_catalog(FALLBACK_LANGUAGE)
        self._subscribers: list[Callable[[], None]] = []
        self.set_language(DEFAULT_LANGUAGE, notify=False)

    # ------------------------------------------------------------------ API
    @property
    def language(self) -> str:
        return self._language

    def set_language(self, code: str, *, notify: bool = True) -> bool:
        """Activate ``code``; unknown codes are rejected. Returns success."""
        if code not in AVAILABLE_LANGUAGES:
            logger.warning("Unknown language code: %s", code)
            return False
        self._catalog = self._load_catalog(code)
        self._language = code
        logger.info("Language switched to %s", code)
        if notify:
            for callback in list(self._subscribers):
                callback()
        return True

    def tr(self, key: str, **kwargs: object) -> str:
        """Translate ``key``; optional ``str.format`` arguments.

        Missing keys return the key itself (visible in the UI -> easy to
        spot untranslated strings during development).
        """
        text = self._catalog.get(key) or self._fallback.get(key) or key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                logger.warning("Bad format args for i18n key %s", key)
        return text

    def subscribe(self, callback: Callable[[], None]) -> None:
        """Register a retranslate callback (idempotent)."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ------------------------------------------------------------- internal
    def _load_catalog(self, code: str) -> dict[str, str]:
        path = self._i18n_dir / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("catalog root must be an object")
            return {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError) as exc:
            logger.error("Failed to load i18n catalog %s: %s", path, exc)
            return {}


#: Process-wide singleton used by the whole UI layer.
localization = LocalizationManager()


def tr(key: str, **kwargs: object) -> str:
    """Module-level convenience wrapper around the singleton."""
    return localization.tr(key, **kwargs)
