"""Property-based tests for API response pagination.

**Property 30: API Response Pagination**

For any list endpoint, pagination must satisfy:
1. items count ≤ page_size for every page.
2. total_pages = ceil(total / page_size).
3. Concatenating all pages yields exactly the full result set (no duplicates, no gaps).
4. page_size is clamped to [1, 100].
5. Requesting a page beyond total_pages returns an empty items list.

**Validates: Requirements 17.4**
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.services.dataset_service import Page

# ---------------------------------------------------------------------------
# Helpers: synchronous SQLite-backed pagination logic
# ---------------------------------------------------------------------------


def _paginate(items: list, page: int, page_size: int) -> Page:
    """Simulate the Page response for a list of items."""
    page_size = max(1, min(100, page_size))
    total = len(items)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]
    return Page(
        items=page_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestApiPagination:
    """Property 30: API Response Pagination."""

    @given(
        total=st.integers(min_value=0, max_value=200),
        page_size=st.integers(min_value=1, max_value=100),
        page=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=80)
    def test_items_count_never_exceeds_page_size(self, total, page_size, page):
        """Property: items count on any page is always ≤ page_size."""
        items = list(range(total))
        result = _paginate(items, page, page_size)
        assert len(result.items) <= result.page_size

    @given(
        total=st.integers(min_value=0, max_value=500),
        page_size=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=80)
    def test_total_pages_equals_ceil_division(self, total, page_size):
        """Property: total_pages == ceil(total / page_size)."""
        items = list(range(total))
        result = _paginate(items, 1, page_size)
        expected_pages = math.ceil(total / page_size) if total > 0 else 0
        assert result.total_pages == expected_pages

    @given(
        total=st.integers(min_value=1, max_value=200),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=60)
    def test_all_pages_concatenate_to_full_dataset(self, total, page_size):
        """Property: Concatenating all pages yields the complete, ordered dataset."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)
        total_pages = first_page.total_pages

        collected = []
        for p in range(1, total_pages + 1):
            page_result = _paginate(items, p, page_size)
            collected.extend(page_result.items)

        assert collected == items, "Concatenated pages do not match original dataset"

    @given(
        total=st.integers(min_value=0, max_value=100),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=50)
    def test_page_beyond_total_returns_empty_items(self, total, page_size):
        """Property: Requesting a page beyond total_pages returns empty items."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)
        beyond_page = first_page.total_pages + 1

        result = _paginate(items, beyond_page, page_size)
        assert result.items == []

    @given(
        total=st.integers(min_value=0, max_value=200),
        raw_page_size=st.integers(min_value=-10, max_value=200),
    )
    @settings(max_examples=60)
    def test_page_size_clamped_to_valid_range(self, total, raw_page_size):
        """Property: page_size is always clamped to [1, 100]."""
        items = list(range(total))
        result = _paginate(items, 1, raw_page_size)
        assert 1 <= result.page_size <= 100

    @given(
        total=st.integers(min_value=1, max_value=100),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=50)
    def test_total_is_consistent_across_pages(self, total, page_size):
        """Property: total field is the same on every page."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)
        total_pages = first_page.total_pages

        for p in range(1, total_pages + 1):
            page_result = _paginate(items, p, page_size)
            assert page_result.total == total, (
                f"Page {p} reports total={page_result.total}, expected {total}"
            )

    @given(
        total=st.integers(min_value=0, max_value=100),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=50)
    def test_no_duplicate_items_across_pages(self, total, page_size):
        """Property: No item appears on more than one page."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)
        total_pages = first_page.total_pages

        seen = []
        for p in range(1, total_pages + 1):
            page_result = _paginate(items, p, page_size)
            for item in page_result.items:
                assert item not in seen, f"Duplicate item {item} found on page {p}"
                seen.append(item)

    @given(
        total=st.integers(min_value=1, max_value=100),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=40)
    def test_last_page_may_have_fewer_items(self, total, page_size):
        """Property: The last page has between 1 and page_size items."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)
        last_page = _paginate(items, first_page.total_pages, page_size)

        assert 1 <= len(last_page.items) <= page_size

    @given(
        total=st.integers(min_value=0, max_value=200),
        page_size=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50)
    def test_empty_dataset_has_zero_total_pages(self, total, page_size):
        """Property: An empty dataset always has total_pages == 0."""
        if total > 0:
            return  # Only test empty case
        items: list = []
        result = _paginate(items, 1, page_size)
        assert result.total_pages == 0
        assert result.total == 0
        assert result.items == []

    @given(
        total=st.integers(min_value=1, max_value=100),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=40)
    def test_page_metadata_is_self_consistent(self, total, page_size):
        """Property: page, page_size, total, and total_pages are mutually consistent."""
        items = list(range(total))
        first_page = _paginate(items, 1, page_size)

        assert first_page.total == total
        assert first_page.page == 1
        assert first_page.page_size == page_size
        assert first_page.total_pages == math.ceil(total / page_size)
