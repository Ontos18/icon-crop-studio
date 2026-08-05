"""Paged collection of images with a current selection (Qt-free).

Holds ALL image paths (cheap: just paths + status enums, fine for 5000+
files) but exposes them one page at a time — the UI only ever touches the
current page, which is what keeps the thumbnail panel fast.

Page state and selection are linked in one direction only:
selecting an image moves the visible page to it (so keyboard navigation
"next image" flows across page borders), but merely browsing pages does
NOT change the selection.
"""
from __future__ import annotations

from pathlib import Path

from models.image_item import ImageItem


class ImageCollection:
    """Ordered image list + pagination + current selection."""

    def __init__(self, page_size: int = 20) -> None:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        self._page_size = page_size
        self._items: list[ImageItem] = []
        #: path -> global index, kept in sync by load/append/remove so that
        #: path lookups (e.g. per-export status updates) are O(1).
        self._index: dict[Path, int] = {}
        self._current_index: int = -1   # -1 = no selection
        self._current_page: int = 0

    # ---------------------------------------------------------- basic state
    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[ImageItem]:
        return self._items

    @property
    def page_size(self) -> int:
        return self._page_size

    def set_page_size(self, size: int) -> None:
        if size < 1:
            raise ValueError("page_size must be >= 1")
        self._page_size = size
        self._current_page = min(self._current_page, self.page_count - 1)

    # -------------------------------------------------------------- loading
    def load(self, paths: list[Path]) -> None:
        """Replace the whole collection (new folder opened)."""
        self._items = [ImageItem(p) for p in paths]
        self._rebuild_index()
        self._current_index = -1
        self._current_page = 0

    def append(self, paths: list[Path]) -> int:
        """Add paths not already present (drag & drop / folder watch).

        Returns the number of items actually added.
        """
        added = 0
        for path in paths:
            if path in self._index:
                continue
            self._items.append(ImageItem(path))
            self._index[path] = len(self._items) - 1
            added += 1
        return added

    def remove(self, paths: list[Path]) -> int:
        """Remove images by path (folder watch). Returns count removed.

        If the selected item is removed, the selection falls back to the item
        that shifted into its slot (clamped to the new length); an emptied
        collection clears the selection and returns to page 0.
        """
        doomed = {p for p in paths}
        kept = [item for item in self._items if item.path not in doomed]
        removed = len(self._items) - len(kept)
        if not removed:
            return 0
        self._items = kept
        self._rebuild_index()
        # keep current_index pointing at the same slot (clamped), as planned
        self._current_index = min(self._current_index, len(self._items) - 1)
        if self._current_index < 0:
            self._current_page = 0
        else:
            self._current_page = self.page_of_index(self._current_index)
        return removed

    def index_of(self, path: Path) -> int:
        """Global index of ``path``, or -1 if not present (O(1))."""
        return self._index.get(path, -1)

    def clear(self) -> None:
        self.load([])

    # ----------------------------------------------------------- pagination
    @property
    def page_count(self) -> int:
        """At least 1, so the UI can always show 'page 1 / 1'."""
        return max(1, -(-len(self._items) // self._page_size))

    @property
    def current_page(self) -> int:
        return self._current_page

    def items_on_page(self, page: int | None = None) -> list[tuple[int, ImageItem]]:
        """(global_index, item) pairs for ``page`` (default: current page)."""
        p = self._current_page if page is None else page
        start = p * self._page_size
        return list(enumerate(self._items[start:start + self._page_size],
                              start=start))

    def go_to_page(self, page: int) -> bool:
        """Clamp-free page jump; returns False if out of range or no-op."""
        if 0 <= page < self.page_count and page != self._current_page:
            self._current_page = page
            return True
        return False

    def next_page(self) -> bool:
        return self.go_to_page(self._current_page + 1)

    def prev_page(self) -> bool:
        return self.go_to_page(self._current_page - 1)

    # ------------------------------------------------------------ selection
    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_item(self) -> ImageItem | None:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return None

    def page_of_index(self, index: int) -> int:
        return index // self._page_size

    def select(self, index: int) -> bool:
        """Select by global index and bring its page into view."""
        if not 0 <= index < len(self._items):
            return False
        self._current_index = index
        self._current_page = self.page_of_index(index)
        return True

    def select_next(self) -> bool:
        """Move selection forward (starts at 0 when nothing is selected)."""
        return self.select(self._current_index + 1)

    def select_prev(self) -> bool:
        if self._current_index <= 0:
            return False
        return self.select(self._current_index - 1)

    # -------------------------------------------------------------- internal
    def _rebuild_index(self) -> None:
        self._index = {item.path: i for i, item in enumerate(self._items)}
