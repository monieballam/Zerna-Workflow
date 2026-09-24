"""Property-based tests for Zerna label index.

# Feature: gap-analysis-and-verification, Property 43: Zerna label index lookup completeness

**Validates: Requirements 22.1, 22.2**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.annotation.zerna_index import (
    ZernaEntry,
    ZernaLabelIndex,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Build a fresh index for strategies to reference
_INDEX = ZernaLabelIndex()
_ALL_CANONICAL = [e.canonical_label for e in _INDEX.entries]
_ALL_ALIASES: list[str] = []
for _entry in _INDEX.entries:
    _ALL_ALIASES.extend(_entry.aliases)

_ALL_KNOWN_LABELS = _ALL_CANONICAL + _ALL_ALIASES

_canonical_label_st = st.sampled_from(_ALL_CANONICAL)
_alias_st = st.sampled_from(_ALL_ALIASES)
_any_known_label_st = st.sampled_from(_ALL_KNOWN_LABELS)


# ---------------------------------------------------------------------------
# Property 43: Zerna label index lookup completeness
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestZernaLabelIndexLookupCompleteness:
    """Property 43: Zerna label index lookup completeness.

    For any label in the Zerna index, lookup must return canonical_label,
    ontology_id, aliases, and hierarchy_path. Looking up the canonical label
    must return the same entry (idempotent lookup).
    """

    @given(label=_any_known_label_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_lookup_returns_complete_entry(self, label: str) -> None:
        """# Feature: gap-analysis-and-verification, Property 43: Zerna label index lookup completeness

        **Validates: Requirements 22.1, 22.2**

        For any known label (canonical or alias), lookup must return an entry
        with all required fields populated.
        """
        index = ZernaLabelIndex()
        entry = index.lookup(label)

        assert entry is not None, f"Lookup for known label '{label}' returned None"
        assert isinstance(entry, ZernaEntry)

        # canonical_label must be a non-empty string
        assert isinstance(entry.canonical_label, str)
        assert len(entry.canonical_label) > 0

        # ontology_id must match CL:XXXXXXX pattern
        assert isinstance(entry.ontology_id, str)
        assert entry.ontology_id.startswith("CL:")
        assert len(entry.ontology_id) > 3

        # aliases must be a list
        assert isinstance(entry.aliases, list)

        # hierarchy_path must be a non-empty list of strings
        assert isinstance(entry.hierarchy_path, list)
        assert len(entry.hierarchy_path) > 0
        assert all(isinstance(p, str) and len(p) > 0 for p in entry.hierarchy_path)

    @given(label=_canonical_label_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_canonical_lookup_is_idempotent(self, label: str) -> None:
        """# Feature: gap-analysis-and-verification, Property 43: Zerna label index lookup completeness

        **Validates: Requirements 22.1, 22.2**

        Looking up the canonical label must return an entry whose
        canonical_label matches, and looking up that canonical_label again
        must return the exact same entry.
        """
        index = ZernaLabelIndex()
        entry = index.lookup(label)

        assert entry is not None, f"Canonical label '{label}' not found"
        assert entry.canonical_label == label

        # Idempotent: looking up the canonical_label from the result
        # must return the same entry
        entry2 = index.lookup(entry.canonical_label)
        assert entry2 is not None
        assert entry2 == entry

    @given(alias=_alias_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_alias_resolves_to_canonical(self, alias: str) -> None:
        """# Feature: gap-analysis-and-verification, Property 43: Zerna label index lookup completeness

        **Validates: Requirements 22.1, 22.2**

        Looking up an alias must return an entry, and looking up that entry's
        canonical_label must return the same entry (alias -> canonical round-trip).
        """
        index = ZernaLabelIndex()
        entry = index.lookup(alias)

        assert entry is not None, f"Alias '{alias}' not found"

        # The alias must appear in the entry's aliases list
        alias_lower_set = {a.lower() for a in entry.aliases}
        assert alias.lower() in alias_lower_set, (
            f"Alias '{alias}' not in entry aliases: {entry.aliases}"
        )

        # Round-trip: canonical lookup must return the same entry
        canonical_entry = index.lookup(entry.canonical_label)
        assert canonical_entry is not None
        assert canonical_entry == entry

    @given(label=_any_known_label_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_case_insensitive_lookup(self, label: str) -> None:
        """Lookup must be case-insensitive for all known labels."""
        index = ZernaLabelIndex()

        entry_original = index.lookup(label)
        entry_upper = index.lookup(label.upper())
        entry_lower = index.lookup(label.lower())

        assert entry_original is not None
        assert entry_upper == entry_original
        assert entry_lower == entry_original

    @given(labels=st.lists(_any_known_label_st, min_size=1, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_harmonize_returns_entries_for_all_known_labels(self, labels: list[str]) -> None:
        """harmonize must return a non-None entry for every known label."""
        index = ZernaLabelIndex()
        results = index.harmonize(labels)

        assert len(results) == len(labels)
        for i, result in enumerate(results):
            assert result is not None, f"harmonize returned None for known label '{labels[i]}'"
            assert isinstance(result, ZernaEntry)
