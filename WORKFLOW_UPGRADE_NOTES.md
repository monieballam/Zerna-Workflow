# Single-cell workflow upgrade (zerna-platform)

## Default ordered workflow

1. Load raw counts (per sample when multi-file; existing ingestion).
2. **QC & filtering** — compute `n_genes_by_counts`, `total_counts`, `pct_counts_mt`, optional ribo / HK / HB metrics; filter cells with per-rule counts; filter genes by `min_cells`.
3. **Doublet detection** (default **Scrublet**, per-sample when `batch_key` / `doublet_sample_key` exists) — scores + calls; **remove** or **flag-only** via `doublet_mode`.
4. **Ambient correction** (optional, off by default) — `off` skips processing; `identity` copies raw counts to `layers["corrected_counts"]` for pipeline provenance and sets `zerna_active_counts_layer` — it does **not** remove ambient RNA. `soupx` runs through an R helper. Because this pipeline step does not retain the raw empty-droplet matrix, the worker uses a filtered-counts-only SoupX approximation: the filtered count matrix is used as both `toc` and `tod`, and the soup profile is derived from filtered counts. Honest status is always written to `adata.uns["zerna_ambient_correction"]` and mirrored in step metrics / `run_summary.json` (see below).
5. **Normalization** — preserve `layers["counts"]`; normalize from `layers["counts"]` or active layer (`zerna_active_counts_layer`); target sum **1e4** + **log1p** to `X` and `layers["log1p"]`.
6. **HVG** — **seurat_v3** on **counts** layer when present; batch-aware if `hvg_batch_key` / `batch_key` resolves; **no subset** (Scanpy flags only); provenance in `uns["zerna_hvg"]`.
7. **PCA** — HVG-masked; sets `uns["zerna_active_representation"] = "X_pca"`.
8. **Batch correction** (optional) — **`batch_method` default is Harmony**; **`integration_mode`** overrides `batch_method` when set (`harmony` | `scvi`). Harmony → `X_pca_harmony`; scVI → `X_scVI`. Both set `uns["zerna_integration"]` and refresh `zerna_active_representation`.
9. **Neighbors + Leiden** (default) — `use_rep` from `zerna_active_representation` unless overridden; sklearn KNN transformer to avoid fragile Numba/TBB in workers.
10. **UMAP** (default embedding) — same `use_rep` policy.
11. **Annotation / DE** — unchanged modular steps.

## Optional paths

| Area        | Knobs                                                                                                                  |
| ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| QC          | `min_counts`, `max_counts`, `max_ribo_pct`, `max_hk_pct`, `compute_hb_pct` + `max_hb_pct`                              |
| Doublets    | `doublet_mode`: `flag_only` \| `remove_doublets`; `doublet_sample_key`; backends unchanged (SOLO, DoubletDetection, R) |
| Ambient     | Run param `ambient_correction: true` + `ambient_method`                                                                |
| Integration | `batch_correction: true`, `batch_key` required; `integration_mode` or `batch_method`                                   |
| Embedding   | `embedding_method`: `umap` \| `tsne`; clustering: `clustering_method`: `leiden` \| `louvain`                           |

## Artifacts & provenance

- Per step: `uns["zerna_provenance"]["steps"]` appended after each successful `_run_step`.
- QC: `qc_report/qc_summary.json`, `qc_report/qc_metrics.csv` (when QC report present).
- Run rollup: `qc_report/run_summary.json` (provenance + `zerna_*` blocks + `step_metrics`).
- Doublets: `uns["zerna_doublet_summary"]` (method, parameters, per-sample counts).
- Ambient (when the step runs): `uns["zerna_ambient_correction"]` with explicit fields so UIs and summaries never imply real ambient removal when it did not happen:
  - `requested_method` — run parameter (`off` | `identity` | `soupx`).
  - `applied_method` — what the worker actually did (`off`, `identity`, or `soupx`).
  - `status` — e.g. `not_applied`, `identity_scaffold_only` (identity copy only; **not** biological correction), `soupx_applied_filtered_counts_only`.
  - `message` — short human-readable explanation.
  - `source_layer`, `output_layer`, `active_counts_layer` — layer bookkeeping for downstream normalization.
  - `estimated_contamination_fraction`, `soup_profile_source`, `cluster_count` — provenance for the SoupX run.

## What changed vs previous Kiro behavior

- **QC** is richer (ribo/HK/HB options, UMI bounds, per-rule removal table in `zerna_qc_report`).
- **Default `max_genes`** in the worker mapping aligned to **6000** (catalog already used 6000).
- **Batch default** is **Harmony**, not scVI (`batch_method` default + `integration_mode` hook).
- **Normalization** returns **metrics** and records **`zerna_normalization`** (source layer).
- **Representation** for neighbors / UMAP / Leiden is **explicit** via `zerna_active_representation` after PCA / integration.
- **New optional step** `ambient_correction` in catalog and dependencies (off unless `ambient_correction: true`).
- **Template API read-path**: stored pipeline templates are **non-destructively** merged with the current catalog dependency rules when returned from the API (`normalize_pipeline_template_definition`). Older rows missing edges such as `normalize` → `ambient_correction` gain only missing edges; existing edges are kept. When any edge was added, `definition.metadata.dependency_edges_merged_from_catalog` is `true`.
- **Doublet** metrics include **per-sample** breakdown and **`doublet_mode`**; legacy `filter_doublets` still works unless `doublet_mode` is set.

## What we borrowed from the legacy Zerna mindset (not copied code)

- Biology-aware QC: **ribosomal** and **housekeeping/ambient-associated** fractions, optional **hemoglobin** for blood contexts, **UMI** min/max filters.
- Clear **per-stage filtering accountability** (cells removed per rule).
- **Per-sample doublet** behavior when sample/batch columns exist.

## Files touched (summary)

| Area                          | Files                                                                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| QC                            | `methods/preprocessing/qc_filter.py`                                                                                           |
| Ambient                       | `methods/preprocessing/ambient_correction.py` (new)                                                                            |
| Norm                          | `methods/preprocessing/normalization.py`                                                                                       |
| Doublet                       | `methods/preprocessing/doublet_detection.py`                                                                                   |
| HVG                           | `methods/preprocessing/hvg_selection.py`                                                                                       |
| PCA / batch / cluster / embed | `methods/dimensionality_reduction/{pca,batch_correction,clustering,embedding}.py`                                              |
| Provenance                    | `methods/pipeline/provenance.py`, `methods/pipeline/__init__.py` (new)                                                         |
| Orchestration                 | `workflows/run_execution/activities.py`                                                                                        |
| Catalog / UI                  | `apps/api/services/pipeline_catalog.py`, `apps/web/lib/pipeline-catalog.ts`, `apps/web/lib/pipeline-parameter-presentation.ts` |
