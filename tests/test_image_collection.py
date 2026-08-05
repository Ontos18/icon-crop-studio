"""Unit tests for models.image_collection (no Qt required)."""
from __future__ import annotations

from pathlib import Path

import pytest

from models.image_collection import ImageCollection


def _paths(n: int) -> list[Path]:
    return [Path(f"img_{i:03d}.png") for i in range(n)]


def test_empty_collection() -> None:
    c = ImageCollection(page_size=20)
    assert len(c) == 0
    assert c.page_count == 1            # UI can always show "1 / 1"
    assert c.current_item is None
    assert c.select_next() is False or c.current_index == 0


def test_page_count_and_page_items() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(45))
    assert c.page_count == 3
    assert [i for i, _ in c.items_on_page(0)] == list(range(20))
    assert [i for i, _ in c.items_on_page(2)] == list(range(40, 45))


def test_page_navigation_bounds() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(45))
    assert c.prev_page() is False       # already at first page
    assert c.next_page() is True and c.current_page == 1
    assert c.next_page() is True and c.current_page == 2
    assert c.next_page() is False       # at last page
    assert c.go_to_page(99) is False


def test_selection_moves_page() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(45))
    assert c.select(41) is True
    assert c.current_page == 2
    # Browsing pages must NOT move the selection.
    c.go_to_page(0)
    assert c.current_index == 41


def test_select_next_crosses_page_border() -> None:
    c = ImageCollection(page_size=2)
    c.load(_paths(3))
    assert c.select_next() and c.current_index == 0
    assert c.select_next() and c.current_index == 1
    assert c.select_next() and c.current_index == 2 and c.current_page == 1
    assert c.select_next() is False     # end of list


def test_select_prev_at_start() -> None:
    c = ImageCollection(page_size=2)
    c.load(_paths(3))
    c.select(0)
    assert c.select_prev() is False


def test_append_deduplicates() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(3))
    added = c.append([Path("img_001.png"), Path("new.png")])
    assert added == 1
    assert len(c) == 4


def test_index_of() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(5))
    assert c.index_of(Path("img_003.png")) == 3
    assert c.index_of(Path("nope.png")) == -1


def test_append_updates_index() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(3))
    c.append([Path("new.png")])
    assert c.index_of(Path("new.png")) == 3


def test_remove_items_and_fix_index() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(5))
    removed = c.remove([Path("img_001.png"), Path("img_003.png")])
    assert removed == 2
    assert len(c) == 3
    assert c.index_of(Path("img_000.png")) == 0
    assert c.index_of(Path("img_002.png")) == 1
    assert c.index_of(Path("img_004.png")) == 2


def test_remove_nonexistent_returns_zero() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(3))
    assert c.remove([Path("nope.png")]) == 0
    assert len(c) == 3


def test_remove_current_item_falls_back_to_next() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(5))
    c.select(2)                          # 当前项 img_002
    c.remove([Path("img_002.png")])
    assert c.current_index == 2          # 索引保持指向后移项
    assert c.current_item.name == "img_003.png"


def test_remove_last_item_clamps_selection() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(3))
    c.select(2)
    c.remove([Path("img_002.png")])
    assert c.current_index == 1
    assert c.current_item.name == "img_001.png"


def test_remove_all_clears_selection_and_page() -> None:
    c = ImageCollection(page_size=20)
    c.load(_paths(2))
    c.select(1)
    c.remove([Path("img_000.png"), Path("img_001.png")])
    assert c.current_index == -1
    assert c.current_page == 0
    assert c.current_item is None


def test_remove_recomputes_current_page() -> None:
    c = ImageCollection(page_size=2)
    c.load(_paths(6))
    c.select(5)                          # 第 3 页
    c.remove([Path("img_004.png"), Path("img_005.png")])
    assert c.current_index == 3
    assert c.current_page == 1           # 翻回上一页
    assert c.current_item.name == "img_003.png"


def test_load_resets_state() -> None:
    c = ImageCollection(page_size=2)
    c.load(_paths(5))
    c.select(4)
    c.load(_paths(2))
    assert c.current_index == -1
    assert c.current_page == 0


def test_invalid_page_size_rejected() -> None:
    with pytest.raises(ValueError):
        ImageCollection(page_size=0)


def test_set_page_size_clamps_current_page() -> None:
    c = ImageCollection(page_size=2)
    c.load(_paths(10))
    c.go_to_page(4)
    c.set_page_size(20)
    assert c.current_page == 0
    assert c.page_count == 1
