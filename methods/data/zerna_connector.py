"""Zerna knowledge-base connector.

Queries the external Zerna knowledge base for marker genes, cell type
definitions, and pathway annotations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Marker:
    """A marker gene associated with a cell type."""

    gene: str
    cell_type: str
    source: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class Pathway:
    """A biological pathway annotation."""

    pathway_id: str
    name: str
    genes: tuple[str, ...] = ()
    source: str = ""


class ZernaConnector:
    """Client for querying the Zerna external knowledge base.

    In production this would issue HTTP/gRPC calls to the Zerna service.
    The constructor accepts an optional *base_url*; when ``None`` the
    connector operates against a built-in stub dataset so that tests and
    offline development work without a running service.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url
        # Built-in stub data for offline / test usage
        self._stub_markers: dict[str, list[Marker]] = {}
        self._stub_pathways: dict[str, list[Pathway]] = {}

    # ------------------------------------------------------------------
    # Stub data helpers (for testing / offline mode)
    # ------------------------------------------------------------------

    def register_markers(self, cell_type: str, markers: list[Marker]) -> None:
        """Register stub markers for *cell_type* (offline mode)."""
        self._stub_markers[cell_type] = list(markers)

    def register_pathways(self, gene: str, pathways: list[Pathway]) -> None:
        """Register stub pathways for *gene* (offline mode)."""
        self._stub_pathways[gene] = list(pathways)

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def query_markers(self, cell_type: str) -> list[Marker]:
        """Return marker genes for *cell_type*.

        When running against the stub dataset, returns previously
        registered markers.  Returns an empty list when no markers are
        known for the requested cell type.
        """
        if self._base_url is not None:
            # In production, this would call the remote service.
            # Placeholder for HTTP client integration.
            raise NotImplementedError("Remote Zerna queries are not yet implemented")
        return list(self._stub_markers.get(cell_type, []))

    def query_pathways(self, gene_set: list[str]) -> list[Pathway]:
        """Return pathway annotations covering any gene in *gene_set*.

        Deduplicates pathways that appear for multiple genes.
        """
        if self._base_url is not None:
            raise NotImplementedError("Remote Zerna queries are not yet implemented")
        seen_ids: set[str] = set()
        results: list[Pathway] = []
        for gene in gene_set:
            for pw in self._stub_pathways.get(gene, []):
                if pw.pathway_id not in seen_ids:
                    seen_ids.add(pw.pathway_id)
                    results.append(pw)
        return results
