"""Ligand-receptor interaction analysis method using LIANA."""

from __future__ import annotations

import io
from collections.abc import Iterable

import anndata as ad
import pandas as pd
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.annotation.species import resolve_species
from methods.base import MethodDefinition


class LigandReceptorInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    communication_grouping: str = Field(
        default="auto",
        description=(
            "LIANA groupby: 'auto' tries cci_celltype_minor, then cci_celltype_fine, "
            "then cci_celltype_major, else cluster (with recorded fallback). "
            "'cci_major'|'cci_minor'|'cci_fine' require the matching cci_celltype_* column "
            "from AnnotationAgentV3 (no silent cluster fallback). "
            "'cluster' uses cluster_key only. "
            "'lineage_subcluster' groups by P2 obs[lineage_subcluster] (advanced; not used by auto)."
        ),
    )
    cluster_key: str = Field(
        default="leiden",
        description=(
            "When communication_grouping is cluster, or as fallback: obs column for clusters. "
            "Also the hint used to resolve leiden/louvain when CCI columns are missing."
        ),
    )
    resource_name: str = Field(
        default="consensus",
        description=(
            "LIANA resource name: 'consensus', 'cellphonedb', 'cellchat', "
            "'connectome', 'natmi', 'scseqcomm', or 'singlecellsignalr'"
        ),
    )
    expr_prop: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Minimum proportion of cells expressing ligand/receptor",
    )
    min_cells: int = Field(
        default=5,
        ge=1,
        description="Minimum cells per cluster to include in analysis",
    )
    n_perms: int = Field(
        default=100,
        ge=0,
        description="Number of permutations for significance testing (0 = skip)",
    )
    species: str = Field(
        default="human",
        description="Species of the expression matrix; used to adapt LIANA resources.",
    )
    verbose: bool = False


class LigandReceptorMetrics(BaseModel):
    n_interactions: int
    n_cluster_pairs: int
    n_clusters: int
    cluster_key: str
    resource_name: str
    lr_communication_grouping_requested: str = "auto"
    lr_communication_grouping_effective: str = "cluster"
    lr_used_cluster_fallback: bool = False
    lr_fallback_reason: str | None = None


class LigandReceptorOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    results_df: pd.DataFrame
    metrics: LigandReceptorMetrics


class LigandReceptorMethod(MethodDefinition):
    """Cell–cell communication via LIANA ``rank_aggregate`` (ligand–receptor).

    Grouping is resolved strictly for explicit annotation modes; ``auto`` may fall
    back to clusters when no valid ``cci_celltype_*`` column exists. See
    :mod:`methods.annotation.lr_communication_grouping` for the annotation contract.

    Results:
      - ``output.results_df`` — tidy table (``source``/``target`` technical keys;
        ``*_display`` for UI)
      - ``adata.uns["liana_res"]`` — LIANA-native payload (backward compatible)
      - ``adata.uns["zerna_ligand_receptor"]`` — audit trail (grouping, species, resource)
    """

    name = "ligand_receptor_analysis"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return LigandReceptorInput

    def output_schema(self):
        return LigandReceptorOutput

    def execute(self, input: LigandReceptorInput, compute) -> LigandReceptorOutput:
        import liana

        from methods.annotation.lr_communication_grouping import (
            add_lr_display_columns,
            resolve_lr_groupby_column,
        )

        adata = input.adata
        cg = (input.communication_grouping or "auto").strip().lower()
        if cg not in (
            "auto",
            "cci_major",
            "cci_minor",
            "cci_fine",
            "cluster",
            "lineage_subcluster",
        ):
            cg = "auto"
        grouping = resolve_lr_groupby_column(
            adata,
            communication_grouping=cg,
            cluster_key_requested=input.cluster_key,
        )
        groupby_key = grouping["groupby_column"]

        resource = _prepare_resource_for_species(
            liana=liana,
            adata=adata,
            resource_name=input.resource_name,
            species=input.species,
        )
        species_resolved = resolve_species(input.species, adata.var_names)
        resource_filtered, resource_gene_overlap = _resource_provenance_stats(
            liana=liana,
            adata=adata,
            resource_name=input.resource_name,
            species=input.species,
            resource_passed_to_rank_aggregate=resource,
        )

        # Filter groups with too few cells
        cluster_counts = adata.obs[groupby_key].value_counts()
        valid_clusters = cluster_counts[cluster_counts >= input.min_cells].index.tolist()
        if len(valid_clusters) < 2:
            raise ValueError(
                f"Need at least 2 groups with >= {input.min_cells} cells for "
                f"ligand-receptor analysis (groupby={groupby_key!r}). "
                f"Found {len(valid_clusters)} valid groups."
            )
        analysis_adata = _prepare_liana_input(
            adata=adata,
            cluster_key=groupby_key,
            valid_clusters=valid_clusters,
            resource=resource,
        )

        # Run LIANA
        liana.mt.rank_aggregate(
            analysis_adata,
            groupby=groupby_key,
            resource_name=input.resource_name,
            resource=resource,
            expr_prop=input.expr_prop,
            n_perms=input.n_perms if input.n_perms > 0 else None,
            verbose=input.verbose,
            use_raw=False,
        )

        # Extract results (technical source/target unchanged; display columns for UI)
        results_df = _extract_liana_results(analysis_adata)
        results_df = add_lr_display_columns(results_df)
        if "liana_res" in analysis_adata.uns:
            adata.uns["liana_res"] = analysis_adata.uns["liana_res"]

        n_clusters = len(valid_clusters)
        n_cluster_pairs = n_clusters * (n_clusters - 1)  # directed pairs

        metrics = LigandReceptorMetrics(
            n_interactions=len(results_df),
            n_cluster_pairs=n_cluster_pairs,
            n_clusters=n_clusters,
            cluster_key=groupby_key,
            resource_name=input.resource_name,
            lr_communication_grouping_requested=grouping["requested_mode"],
            lr_communication_grouping_effective=grouping["effective_mode"],
            lr_used_cluster_fallback=grouping["used_cluster_fallback"],
            lr_fallback_reason=grouping["fallback_reason"],
        )

        adata.uns["zerna_ligand_receptor"] = {
            "lr_method": "liana_rank_aggregate",
            "grouping_requested": grouping["requested_mode"],
            "grouping_resolved": groupby_key,
            "grouping_source_type": grouping["grouping_source_type"],
            "requested_cluster_key": grouping["requested_cluster_key"],
            "resolved_cluster_key": grouping["resolved_cluster_key"],
            "annotation_dependency_required": grouping["annotation_dependency_required"],
            "annotation_dependency_satisfied": grouping["annotation_dependency_satisfied"],
            "fallback_applied": grouping["used_cluster_fallback"],
            "fallback_reason": grouping["fallback_reason"],
            "species_requested": input.species,
            "species_resolved": species_resolved,
            "resource_name": input.resource_name,
            "resource_filtered_to_species": resource_filtered,
            "resource_gene_overlap_count": int(resource_gene_overlap),
            "min_cells": input.min_cells,
            "expr_prop": input.expr_prop,
            "n_perms": input.n_perms,
            "n_interactions": int(len(results_df)),
            "n_cluster_pairs": int(n_cluster_pairs),
        }

        return LigandReceptorOutput(
            adata=adata,
            results_df=results_df,
            metrics=metrics,
        )


def _extract_liana_results(adata: ad.AnnData) -> pd.DataFrame:
    """Extract LIANA results from adata.uns into a tidy DataFrame."""
    if "liana_res" not in adata.uns:
        return pd.DataFrame()

    liana_res = adata.uns["liana_res"]

    df = liana_res.copy() if isinstance(liana_res, pd.DataFrame) else pd.DataFrame(liana_res)

    if df.empty:
        return df

    # Standardise column names — LIANA uses different names across versions
    rename_map = {
        "source": "source",
        "target": "target",
        "ligand_complex": "ligand_complex",
        "receptor_complex": "receptor_complex",
        "liana_rank": "liana_rank",
        "magnitude_rank": "magnitude_rank",
        "specificity_rank": "specificity_rank",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Sort by liana_rank ascending (most significant first)
    if "liana_rank" in df.columns:
        df = df.sort_values("liana_rank").reset_index(drop=True)

    return df


def _resource_provenance_stats(
    *,
    liana,
    adata: ad.AnnData,
    resource_name: str,
    species: str,
    resource_passed_to_rank_aggregate: pd.DataFrame | None,
) -> tuple[bool, int]:
    """(resource_filtered_to_species, count of resource genes present in adata.var_names)."""
    species_resolved = resolve_species(species, adata.var_names)
    var_set = {str(g) for g in adata.var_names}

    def _overlap_gene_count(resource_df: pd.DataFrame) -> int:
        genes = _extract_resource_genes(resource_df)
        return len(genes & var_set)

    if resource_passed_to_rank_aggregate is not None:
        return (
            species_resolved not in {"", "human"},
            _overlap_gene_count(resource_passed_to_rank_aggregate),
        )

    base = liana.resource.select_resource(resource_name).copy()
    filtered = _filter_resource_to_var_names(base, adata.var_names)
    return False, _overlap_gene_count(filtered)


def _prepare_resource_for_species(
    *,
    liana,
    adata: ad.AnnData,
    resource_name: str,
    species: str,
) -> pd.DataFrame | None:
    """Translate/filter LIANA resources so non-human datasets can still run."""
    normalized_species = resolve_species(species, adata.var_names)
    if normalized_species in {"", "human"}:
        return None

    resource = liana.resource.select_resource(resource_name).copy()
    if normalized_species == "mouse":
        resource["ligand"] = resource["ligand"].map(_human_symbol_to_mouse_symbol)
        resource["receptor"] = resource["receptor"].map(_human_symbol_to_mouse_symbol)

    resource = _filter_resource_to_var_names(resource, adata.var_names)
    if resource.empty:
        raise ValueError(
            f"No {normalized_species} ligand-receptor interactions from resource "
            f"'{resource_name}' matched the dataset gene symbols."
        )
    return resource


def _filter_resource_to_var_names(resource: pd.DataFrame, var_names) -> pd.DataFrame:
    """Keep only ligand-receptor pairs whose genes exist in the dataset."""
    valid_genes = {str(gene) for gene in var_names}

    def has_all_subunits(value: str) -> bool:
        return all(part in valid_genes for part in str(value).split("_"))

    mask = resource["ligand"].map(has_all_subunits) & resource["receptor"].map(has_all_subunits)
    return resource.loc[mask].drop_duplicates().reset_index(drop=True)


def _prepare_liana_input(
    *,
    adata: ad.AnnData,
    cluster_key: str,
    valid_clusters: Iterable,
    resource: pd.DataFrame | None,
) -> ad.AnnData:
    """Build a slim AnnData for LIANA with only relevant cells/genes."""
    cluster_mask = adata.obs[cluster_key].isin(list(valid_clusters)).to_numpy()
    filtered = adata[cluster_mask]

    if resource is None:
        return ad.AnnData(
            X=filtered.X.copy() if hasattr(filtered.X, "copy") else filtered.X,
            obs=filtered.obs[[cluster_key]].copy(),
            var=filtered.var.copy(),
        )

    required_genes = _extract_resource_genes(resource)
    var_names = pd.Index(filtered.var_names.astype(str))
    selected_mask = var_names.isin(required_genes)
    if not selected_mask.any():
        raise ValueError("No ligand-receptor resource genes overlap with the filtered dataset")

    slim = ad.AnnData(
        X=filtered.X[:, selected_mask].copy()
        if hasattr(filtered.X, "copy")
        else filtered.X[:, selected_mask],
        obs=filtered.obs[[cluster_key]].copy(),
        var=filtered.var.iloc[selected_mask].copy(),
    )
    slim.obs_names = filtered.obs_names.copy()
    slim.var_names = var_names[selected_mask]
    return slim


def _extract_resource_genes(resource: pd.DataFrame) -> set[str]:
    """Expand LIANA ligand/receptor complexes into a flat gene-symbol set."""
    genes: set[str] = set()
    for column in ("ligand", "receptor"):
        for value in resource[column].dropna().astype(str):
            genes.update(part for part in value.split("_") if part)
    return genes


def _human_symbol_to_mouse_symbol(symbol: str) -> str:
    """Convert human-style uppercase gene symbols to mouse-style title case."""
    return "_".join(_convert_symbol_token(token) for token in str(symbol).split("_"))


def _convert_symbol_token(token: str) -> str:
    if not token:
        return token
    segments = token.split("-")
    converted_segments = []
    for segment in segments:
        if not segment:
            converted_segments.append(segment)
            continue
        if len(segment) == 1:
            converted_segments.append(segment.upper())
            continue
        converted_segments.append(segment[0].upper() + segment[1:].lower())
    return "-".join(converted_segments)


def results_to_csv(results_df: pd.DataFrame) -> bytes:
    """Serialise LIANA results DataFrame to CSV bytes for artifact storage."""
    buf = io.BytesIO()
    results_df.to_csv(buf, index=False)
    return buf.getvalue()
