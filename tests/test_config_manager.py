"""Unit tests for core.config_manager (no Qt required)."""
from __future__ import annotations

import json
from pathlib import Path

from core.config_manager import AppConfig, ConfigManager


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "config.json")
    config = manager.load()
    assert config == AppConfig()
    assert config.language == "zh_CN"
    assert config.thumbnail_page_size == 20


def test_save_and_reload_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    manager.load()
    manager.config.language = "en_US"
    manager.config.selected_sizes = [[16, 16], [256, 256]]
    assert manager.save() is True
    assert path.is_file()

    reloaded = ConfigManager(path).load()
    assert reloaded.language == "en_US"
    assert reloaded.selected_sizes == [[16, 16], [256, 256]]


def test_unknown_keys_ignored_and_missing_keys_defaulted(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": "en_US", "future_key": 42}),
                    encoding="utf-8")
    config = ConfigManager(path).load()
    assert config.language == "en_US"
    assert config.thumbnail_size == 96          # default filled in
    assert not hasattr(config, "future_key")


def test_legacy_size_fields_migrate(tmp_path: Path) -> None:
    """旧版 ico_sizes/custom_sizes 配置自动迁移到统一的 size_entries。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "ico_sizes": [16, 32],
        "custom_sizes": [[100, 200], [800, 800]],
        "selected_custom_sizes": [[100, 200]],
    }), encoding="utf-8")
    config = ConfigManager(path).load()
    assert [16, 16] in config.size_entries
    assert [100, 200] in config.size_entries
    assert [800, 800] in config.size_entries
    assert config.selected_sizes == [[16, 16], [32, 32], [100, 200]]
    assert not hasattr(config, "ico_sizes")


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    config = ConfigManager(path).load()
    assert config == AppConfig()


def test_reset_to_defaults(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "config.json")
    manager.load()
    manager.config.language = "en_US"
    assert manager.reset_to_defaults() == AppConfig()
    assert manager.config.language == "zh_CN"


def test_crop_move_speed_loaded_and_defaulted(tmp_path: Path) -> None:
    """WASD 移速可持久化；配置缺失时回退默认 10。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"crop_move_speed": 25}), encoding="utf-8")
    assert ConfigManager(path).load().crop_move_speed == 25

    missing = tmp_path / "missing.json"
    assert ConfigManager(missing).load().crop_move_speed == 10


def test_wheel_steps_defaulted_and_persisted(tmp_path: Path) -> None:
    """滚轮步长默认值正确；可持久化；配置缺失时回退默认。"""
    assert AppConfig().wheel_resize_step == 100
    assert AppConfig().wheel_zoom_step == 1.25

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"wheel_resize_step": 150,
                                "wheel_zoom_step": 1.5}),
                    encoding="utf-8")
    config = ConfigManager(path).load()
    assert config.wheel_resize_step == 150
    assert config.wheel_zoom_step == 1.5

    missing = tmp_path / "missing.json"
    m2 = ConfigManager(missing).load()
    assert m2.wheel_resize_step == 100
    assert m2.wheel_zoom_step == 1.25


def test_resize_mode_settings_persist(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    manager.load()
    manager.config.processing_mode = "resize"
    manager.config.resize_axis = "height"
    manager.config.resize_value = 400
    assert manager.save()

    loaded = ConfigManager(path).load()
    assert loaded.processing_mode == "resize"
    assert loaded.resize_axis == "height"
    assert loaded.resize_value == 400
