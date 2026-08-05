"""Unit tests for core.localization (no Qt required)."""
from __future__ import annotations

import json
from pathlib import Path

from core.localization import (
    AVAILABLE_LANGUAGES, LocalizationManager, localization, tr,
)


def test_all_languages_have_catalog_files() -> None:
    i18n_dir = Path(__file__).resolve().parent.parent / "resources" / "i18n"
    for code in AVAILABLE_LANGUAGES:
        assert (i18n_dir / f"{code}.json").is_file(), f"missing {code}.json"


def test_catalogs_have_identical_keys() -> None:
    """Every language must translate exactly the same key set."""
    i18n_dir = Path(__file__).resolve().parent.parent / "resources" / "i18n"
    key_sets = {
        code: set(json.loads((i18n_dir / f"{code}.json")
                             .read_text(encoding="utf-8")))
        for code in AVAILABLE_LANGUAGES
    }
    reference_code, reference_keys = next(iter(key_sets.items()))
    for code, keys in key_sets.items():
        assert keys == reference_keys, (
            f"{code} differs from {reference_code}: "
            f"missing={reference_keys - keys} extra={keys - reference_keys}")


def test_switch_language_changes_translation() -> None:
    manager = LocalizationManager()
    assert manager.set_language("zh_CN") is True
    zh = manager.tr("status.ready")
    assert manager.set_language("en_US") is True
    en = manager.tr("status.ready")
    assert zh != en
    assert en == "Ready"


def test_unknown_language_rejected() -> None:
    manager = LocalizationManager()
    before = manager.language
    assert manager.set_language("xx_XX") is False
    assert manager.language == before


def test_missing_key_returns_key_itself() -> None:
    assert tr("no.such.key") == "no.such.key"


def test_format_arguments() -> None:
    manager = LocalizationManager()
    manager.set_language("en_US")
    assert manager.tr("status.images_loaded", count=42) == "42 images loaded"


def test_subscribers_notified_on_switch() -> None:
    manager = LocalizationManager()
    calls: list[str] = []
    manager.subscribe(lambda: calls.append(manager.language))
    manager.set_language("en_US")
    manager.set_language("zh_CN")
    assert calls == ["en_US", "zh_CN"]


def test_global_singleton_tr() -> None:
    localization.set_language("zh_CN")
    assert tr("status.ready") == "就绪"
