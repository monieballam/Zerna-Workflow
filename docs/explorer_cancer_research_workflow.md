# Cancer-oriented explorer and P2 lineage geometry

This note locks the **product mode** for tumor-microenvironment workflows in the run explorer and downstream annotation geometry.

## P2 lineage reclustering scope (intentional divergence from strict bioze parity)

**Bioze / historical parity:** P2 lineage-local UMAP + `lineage_subcluster` partitions were defined for **Immune** and **Stromal** only.

**Zerna Kiro cancer-oriented mode (current):** P2 also runs for **Epithelial** and **Endothelial**, filling `X_umap_lineage_epithelial` and `X_umap_lineage_endothelial` with the same Scanpy subset pipeline (HVG → PCA → neighbors → UMAP → Leiden) and writing `Epithelial:*` / `Endothelial:*` tokens.

This is an **intentional cancer-research extension**: epithelial and endothelial compartments are routinely inspected in TME studies, and lineage-local embeddings improve interpretability when geometry exists. It is **not** a claim of upstream bioze parity; parity notes in `docs/annotation_parity_gap_map.md` remain the reference for cross-port expectations.

Configuration keys: `epithelial_min_cells`, `endothelial_min_cells` (defaults in `hierarchy_vocabulary.py`), alongside immune/stromal minima.

## Explorer hierarchy filters (canonical artifacts)

- **Lineage** (primary): broad `auto_level1`.
- **Major type (`level2`)** and **fine subtype (`level3`)** (Advanced): cohort filter values are **branch-scoped** using `hierarchy_filter_axes` from the full artifact so users do not see incompatible lineage + major + fine combinations that would yield empty cohorts.
- **Structural L3 only** for filter chips on modern runs: normalized `auto_level3` / `level3_final_safe` — not `rawAnnotationLabel` buckets.
- **Immune singleton L3:** `Mast cells` and `Plasma cells` use structural L3 equal to their L2 label when no finer ontology applies (`IMMUNE_SINGLETON_L3_BY_L2` in `hierarchy_vocabulary.py`).

## Lineage-local embedding labels (UI)

Epithelial and endothelial lineage views use the same explicit embedding selector pattern as immune/stromal (`userFacingEmbeddingCoordinateLabel` in `explorer-embedding-views.ts`). Cluster summaries and partition inspector follow existing lineage-view rules; no silent switch away from global coordinates.

## Deployment recommendation (cancer research)

- Prefer **canonical modern** H5AD (full `auto_level1`–`auto_level3`) for explorer cohort filters and structural L3 chips.
- After pipeline upgrades, **re-run** annotation / P2 on artifacts intended for explorer so epithelial/endothelial `obsm` slots and `lineage_subcluster` are populated.
- Treat **legacy** artifacts as display-first for fine subtype: L3 cohort chips are suppressed to avoid raw-engine buckets driving biology filters.

## Known limitations

- **Multi-select lineage + multi-select level2:** Major-type options are the **union** of majors across selected lineages. Selecting two majors that never co-occur on one cell (e.g. `T cells` + `Fibroblasts` with both `Immune` and `Stromal` ticked) can still yield an **empty** cohort (AND semantics). Prefer a single lineage when isolating one major branch.
- **Cardinality:** More than **80** distinct structural L3 values suppresses L3 filter chips (existing guard).
- **P3 fine epithelial/endothelial:** Not implemented; epithelial/endothelial **lineage-local** UMAPs are P2-scale, not fine-branch P3.
