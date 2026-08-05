"""Unit tests for core.image_loader (no Qt required)."""
from __future__ import annotations

from pathlib import Path

from core.image_loader import filter_supported, is_supported_image, scan_directory


def _touch(directory: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        p = directory / name
        p.write_bytes(b"")
        paths.append(p)
    return paths


def test_supported_extensions_case_insensitive() -> None:
    assert is_supported_image(Path("a.PNG"))
    assert is_supported_image(Path("a.JpEg"))
    assert is_supported_image(Path("a.ico"))
    assert not is_supported_image(Path("a.txt"))
    assert not is_supported_image(Path("a.psd"))


def test_scan_directory_filters_and_sorts(tmp_path: Path) -> None:
    _touch(tmp_path, "b.png", "A.jpg", "notes.txt", "c.webp")
    (tmp_path / "subdir").mkdir()      # directories must be ignored
    result = scan_directory(tmp_path)
    assert [p.name for p in result] == ["A.jpg", "b.png", "c.webp"]


def test_scan_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert scan_directory(tmp_path / "nope") == []


def test_filter_supported_drops_missing_and_unsupported(tmp_path: Path) -> None:
    real = _touch(tmp_path, "x.png", "y.txt")
    ghost = tmp_path / "ghost.png"
    assert filter_supported([*real, ghost]) == [real[0]]
