"""Property-based tests for repository pattern round-trip.

# Feature: gap-analysis-and-verification, Property 50: Repository pattern round-trip

**Validates: Requirements 26.3**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from methods.data.repository import InMemoryRepository, Repository

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Keys: non-empty strings using safe path-like characters
_key_st = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-/.",
    ),
).filter(lambda s: s.strip() != "" and not s.startswith("/"))

# Data: arbitrary bytes (including empty)
_data_st = st.binary(min_size=0, max_size=4096)

# Prefix for list operations
_prefix_st = st.text(
    min_size=0,
    max_size=30,
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-/",
    ),
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestRepositoryRoundTrip:
    """Property 50: For any data written via the repository interface,
    reading it back with the same key must return identical bytes.

    **Validates: Requirements 26.3**
    """

    @given(key=_key_st, data=_data_st)
    @settings(max_examples=100)
    def test_write_then_read_returns_identical_bytes(self, key: str, data: bytes) -> None:
        """Writing data and reading it back yields the exact same bytes.

        **Validates: Requirements 26.3**
        """
        repo: Repository = InMemoryRepository()
        repo.write(key, data)
        assert repo.read(key) == data

    @given(key=_key_st, data=_data_st)
    @settings(max_examples=100)
    def test_overwrite_returns_latest_data(self, key: str, data: bytes) -> None:
        """Overwriting a key and reading returns the newest data.

        **Validates: Requirements 26.3**
        """
        repo: Repository = InMemoryRepository()
        repo.write(key, b"old-data")
        repo.write(key, data)
        assert repo.read(key) == data

    @given(key=_key_st, data=_data_st)
    @settings(max_examples=100)
    def test_delete_removes_key(self, key: str, data: bytes) -> None:
        """After deletion, reading the key raises KeyError.

        **Validates: Requirements 26.3**
        """
        repo: Repository = InMemoryRepository()
        repo.write(key, data)
        repo.delete(key)
        with pytest.raises(KeyError):
            repo.read(key)

    @given(
        entries=st.dictionaries(
            keys=_key_st,
            values=_data_st,
            min_size=1,
            max_size=20,
        ),
        prefix=_prefix_st,
    )
    @settings(max_examples=100)
    def test_list_returns_matching_keys(self, entries: dict[str, bytes], prefix: str) -> None:
        """list(prefix) returns exactly the keys that start with prefix.

        **Validates: Requirements 26.3**
        """
        repo: Repository = InMemoryRepository()
        for k, v in entries.items():
            repo.write(k, v)

        listed = repo.list(prefix)
        expected = sorted(k for k in entries if k.startswith(prefix))
        assert listed == expected
