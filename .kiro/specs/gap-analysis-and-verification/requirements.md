# Requirements Document

## Introduction

This document defines the requirements for a comprehensive gap analysis and verification effort between the original Zerna scRNA-seq platform (`scrna_platform` at `Zerna/Zerna/src`) and the new zerna-platform monorepo (`zerna-platform`). The goal is to identify every functional capability present in the old project that is missing or incomplete in the new project, verify that every existing component in the new project works correctly, and produce a prioritized remediation plan. The old project's own gap backlog (G-001 through G-009) is incorporated as a baseline, and additional structural gaps discovered through code-level comparison are added.

## Glossary

- **Old_Project**: The original Zerna scRNA-seq analysis platform located at `Zerna/Zerna/src`, built with Streamlit and a layered Python architecture (`scrna_platform`).
- **New_Project**: The zerna-platform monorepo located at `zerna-platform`, built with FastAPI (backend), Next.js (frontend), Temporal (workflows), and Nextflow (compute).
- **Gap_Analyzer**: The automated or manual process that compares Old_Project capabilities against New_Project capabilities and produces a gap report.
- **Verification_Engine**: The automated test and manual inspection process that validates each New_Project component functions correctly.
- **Annotation_Pipeline**: The end-to-end cell type annotation workflow including marker scoring, hierarchical labeling, guardrails, normalization, and review.
- **Deterministic_Gating_System**: The rule-based cell classification system in Old_Project using marker expression thresholds and hierarchy mappings for myeloid, stromal, and other cell types.
- **Agentic_Annotation**: The AI-assisted annotation system in Old_Project that uses LLM agents to refine and validate cell type labels.
- **Interpreter**: The natural language query system in Old_Project that allows analysts to ask questions about their data in plain English.
- **Explorer**: The interactive embedding visualization system (UMAP/t-SNE) with filtering, coloring, and gene overlay capabilities.
- **Knowledge_Pack**: A versioned bundle of marker genes, taxonomy definitions, and scoring rules used by the Annotation_Pipeline.
- **Run_Manifest**: An immutable record of all parameters, dataset versions, and method versions used in a single pipeline execution.
- **Method_Registry**: A catalog of pluggable scientific methods (doublet detection, integration, DE, etc.) with versioned contracts.
- **Pan_Prostate_Agent**: A specialized analysis agent in Old_Project for pan-prostate cancer datasets with custom markers and dashboards.

## Requirements

### Requirement 1: Dataset Upload and Import Parity (G-001)

**User Story:** As a computational biologist, I want browser-native dataset upload with multi-mode import (single file, multiple files, cloud path) and guided merge UX, so that I can ingest data as flexibly as in the original platform.

#### Acceptance Criteria

1. WHEN a user selects single-file upload mode, THE New_Project SHALL accept `h5ad`, `10x mtx`, `10x h5`, `csv`, and `tsv` files via browser multipart upload and persist the file to object storage.
2. WHEN a user selects multiple-file upload mode, THE New_Project SHALL allow per-file condition and sample metadata assignment before merge.
3. WHEN a user selects cloud-path import mode, THE New_Project SHALL accept `s3://` URIs and register the dataset without requiring browser upload.
4. WHEN multiple files are selected for merge, THE New_Project SHALL validate schema compatibility and report conflicts before proceeding.
5. WHEN a dataset is imported, THE New_Project SHALL generate an immutable dataset version with lineage metadata including parent references, timestamp, user, and schema summary.
6. IF a merge validation fails, THEN THE New_Project SHALL return an actionable error report describing the incompatible fields.

### Requirement 2: Real Pipeline Compute (G-002)

**User Story:** As a computational biologist, I want the pipeline to execute real scientific compute (QC, doublet detection, normalization, HVG selection, PCA, clustering, annotation, DE) on actual dataset artifacts, so that I get scientifically valid results instead of simulated outputs.

#### Acceptance Criteria

1. WHEN a pipeline run is started, THE New_Project SHALL execute each DAG step using real scientific backends (Scanpy, scVI, scDblFinder, etc.) on the bound dataset artifact.
2. THE New_Project SHALL produce step outputs that match the schema contracts defined in `packages/contracts`.
3. WHEN a doublet detection step executes, THE New_Project SHALL use a non-heuristic backend (scDblFinder, SOLO, or Scrublet) and produce per-cell scores, classes, and threshold metadata.
4. WHEN an integration step executes, THE New_Project SHALL use a real integration backend (scVI or Harmony) and produce batch-mixing and bio-conservation quality metrics.
5. WHEN a differential expression step executes, THE New_Project SHALL use a unified service contract with support for at least two statistical methods.
6. IF a pipeline step fails, THEN THE New_Project SHALL persist a checkpoint and allow resume from the failed step.

### Requirement 3: Dataset-to-Run Binding (G-003)

**User Story:** As a bioinformatics lead, I want every pipeline run to be explicitly and immutably linked to a specific dataset version, so that I can guarantee reproducibility and trace results back to their input data.

#### Acceptance Criteria

1. THE New_Project SHALL require a `dataset_version_id` in the run start contract.
2. WHEN a run is started, THE New_Project SHALL record the dataset version checksum in the run manifest.
3. THE New_Project SHALL reject run start requests that do not include a valid dataset version reference.
4. WHEN a run manifest is replayed, THE New_Project SHALL produce the same step outputs for deterministic methods given the same dataset version and parameters.

### Requirement 4: Explorer and Atlas Workflow Parity (G-004)

**User Story:** As a computational biologist, I want interactive embedding exploration, cell type atlas visualization, and overview dashboards in the new platform, so that I can perform the same exploratory analysis workflows available in the original platform.

#### Acceptance Criteria

1. WHEN a run completes, THE New_Project SHALL provide an Embedding Explorer view with filter controls, gene overlay, color-by metadata, and split-view capabilities.
2. WHEN a run completes, THE New_Project SHALL provide a Cell Type Atlas view with marker gene tables, confidence scores, and gene expression plots.
3. THE New_Project SHALL provide an Overview page summarizing dataset statistics, run status, and key quality metrics.
4. WHEN a user applies filters in the Explorer, THE New_Project SHALL update the visualization within 2 seconds for datasets up to 500,000 cells.

### Requirement 5: Run History Persistence and Reload (G-005)

**User Story:** As a computational biologist, I want durable run history with the ability to search, load, and replay previous runs, so that I can compare results over time and reproduce past analyses.

#### Acceptance Criteria

1. THE New_Project SHALL persist all run sessions, checkpoints, and events to a durable database (not in-memory).
2. WHEN a user navigates to the Previous Runs page, THE New_Project SHALL display a searchable list of all past runs with status, timestamp, dataset, and template metadata.
3. WHEN a user selects a previous run, THE New_Project SHALL load the run outputs into Explorer and Atlas views.
4. WHEN a user requests run replay, THE New_Project SHALL re-execute the run using the persisted manifest and dataset version.
5. IF the API process restarts, THEN THE New_Project SHALL retain all run history and checkpoint data.

### Requirement 6: Export Workflow Parity (G-006)

**User Story:** As a computational biologist, I want a full export center with support for multiple output formats and reproducibility reports, so that I can share and archive my analysis results.

#### Acceptance Criteria

1. THE New_Project SHALL provide an Export page accessible from the main navigation.
2. WHEN a user requests export, THE New_Project SHALL support `h5ad`, `csv`, and Seurat-compatible bundle formats.
3. WHEN a user requests export, THE New_Project SHALL include a reproducibility report containing the run manifest, parameter provenance, and method versions.
4. WHEN a user requests plot export, THE New_Project SHALL support PNG and SVG formats for all visualization outputs.

### Requirement 7: Natural Language Analyst Copilot Parity (G-007)

**User Story:** As a wet-lab scientist, I want a natural language query interface that lets me ask questions about my analysis results in plain English, so that I can explore data without writing code.

#### Acceptance Criteria

1. THE New_Project SHALL provide an Interpreter page accessible from the main navigation.
2. WHEN a user submits a natural language query, THE New_Project SHALL parse the query intent (expression lookup, comparison, plot generation) and return results or visualizations.
3. WHEN a query is processed, THE New_Project SHALL persist the query and result in the user's session history.
4. IF a query cannot be parsed, THEN THE New_Project SHALL return a descriptive error with suggested query reformulations.

### Requirement 8: Stub and Volatile Backend Replacement (G-008)

**User Story:** As a platform admin, I want all production-critical backend surfaces to use durable, database-backed storage instead of in-memory or static data, so that the platform is reliable across restarts and deployments.

#### Acceptance Criteria

1. THE New_Project SHALL store project listings in a persistent database with full CRUD operations.
2. THE New_Project SHALL store DAG definitions in a persistent database with version history and ownership metadata.
3. THE New_Project SHALL store run comparison data from persisted run artifacts and metrics, not from in-code static snapshots.
4. WHEN the API service restarts, THE New_Project SHALL retain all project, DAG, and run comparison data.

### Requirement 9: Annotation Input Ergonomics (G-009)

**User Story:** As a computational biologist, I want the annotation workflow to automatically consume outputs from completed pipeline runs, so that I do not need to manually construct JSON payloads to start annotation.

#### Acceptance Criteria

1. WHEN a pipeline run completes clustering, THE New_Project SHALL automatically make cluster results available to the annotation workflow.
2. THE New_Project SHALL allow users to open the annotation workflow directly from a completed run without manual JSON input.
3. WHERE advanced mode is enabled, THE New_Project SHALL still allow manual JSON cluster score payloads as an override option.

### Requirement 10: Deterministic Gating and Hierarchy Mapping System

**User Story:** As a bioinformatics lead, I want the deterministic cell type gating system (marker-threshold-based classification with hierarchy mappings for myeloid, stromal, and general cell types) ported to the new platform, so that rule-based annotation remains available alongside ML-based methods.

#### Acceptance Criteria

1. THE New_Project SHALL implement a deterministic gating module that classifies cells based on marker expression thresholds defined in configurable marker panel YAML/JSON files.
2. THE New_Project SHALL implement hierarchy mapping for general cell types that maps gating results to L1/L2/L3 hierarchical labels.
3. THE New_Project SHALL implement myeloid-specific hierarchy mapping and subtyping using myeloid subtype marker panels.
4. THE New_Project SHALL implement stromal-specific classification (v1 and v2) and stromal subtyping using stromal subtype marker panels.
5. WHEN a deterministic gating run completes, THE New_Project SHALL produce per-cell labels with provenance indicating the gating rule and marker panel version used.

### Requirement 11: Annotation Guardrails and Label Normalization

**User Story:** As a bioinformatics lead, I want annotation guardrails that enforce label consistency, normalization rules, and quality constraints, so that annotation outputs are scientifically valid and consistent across runs.

#### Acceptance Criteria

1. THE New_Project SHALL implement annotation guardrails that validate label assignments against known cell type ontologies and hierarchy constraints.
2. THE New_Project SHALL implement label normalization that maps variant label strings to canonical cell type names.
3. THE New_Project SHALL implement an annotation columns policy that defines which `.obs` columns are required, optional, and protected during annotation.
4. IF an annotation label violates a guardrail rule, THEN THE New_Project SHALL flag the violation and prevent finalization until resolved.

### Requirement 12: Annotation Label Lifecycle

**User Story:** As a bioinformatics lead, I want a complete label lifecycle (draft, validate, finalize, post-finalize guard) with label contracts, so that annotation quality is enforced at every stage.

#### Acceptance Criteria

1. THE New_Project SHALL implement a label contract that defines the required fields, types, and constraints for valid annotation labels.
2. THE New_Project SHALL implement label validation that checks all labels against the label contract before finalization.
3. THE New_Project SHALL implement a finalize step that locks labels and records the finalization timestamp and user.
4. THE New_Project SHALL implement a post-finalize guard that prevents modification of finalized labels without explicit version increment.
5. IF a label fails validation, THEN THE New_Project SHALL return a detailed report of all contract violations.

### Requirement 13: Annotation Utilities and Scoring

**User Story:** As a computational biologist, I want annotation scoring utilities, marker pack loading, taxonomy loading, subtype assignment, and robustness checks, so that annotation quality can be quantified and improved.

#### Acceptance Criteria

1. THE New_Project SHALL implement annotation scoring utilities that compute per-cluster and per-cell confidence scores based on marker expression.
2. THE New_Project SHALL implement a marker pack loader that reads versioned marker gene panels from Knowledge_Pack bundles.
3. THE New_Project SHALL implement a taxonomy loader that reads cell type hierarchies from ontology files.
4. THE New_Project SHALL implement subtype assignment logic that refines broad cell type labels into specific subtypes using marker evidence.
5. THE New_Project SHALL implement a robustness layer that tests annotation stability under perturbation (e.g., subsampling, parameter variation).
6. THE New_Project SHALL implement a Zerna client connector for querying external knowledge base resources.

### Requirement 14: Annotation Evaluation and Marker Provenance

**User Story:** As a bioinformatics lead, I want annotation layer evaluation, marker pack validation, and marker provenance tracking, so that I can audit annotation quality and trace marker gene sources.

#### Acceptance Criteria

1. THE New_Project SHALL implement annotation layer evaluation that compares annotation results across L1/L2/L3 layers and reports consistency metrics.
2. THE New_Project SHALL implement marker pack validation that checks all marker panels against reference datasets and reports sensitivity/specificity.
3. THE New_Project SHALL implement marker provenance tracking that records the source, version, and citation for every marker gene used in annotation.

### Requirement 15: Evidence Scoring and Marker Index

**User Story:** As a computational biologist, I want evidence scoring that quantifies the support for each cell type assignment and a searchable marker index, so that I can understand and audit annotation decisions.

#### Acceptance Criteria

1. THE New_Project SHALL implement evidence scoring that computes a composite confidence score for each cell type assignment based on marker expression, reference mapping, and ontology alignment.
2. THE New_Project SHALL implement a marker index loader that builds a searchable index of all marker genes across all loaded Knowledge_Packs.
3. WHEN a user queries the marker index, THE New_Project SHALL return matching markers with their associated cell types, sources, and confidence weights.

### Requirement 16: Agentic Annotation System

**User Story:** As a bioinformatics lead, I want an AI-assisted annotation system that uses LLM agents to refine uncertain cell type labels and suggest corrections, so that annotation accuracy improves beyond what rule-based methods alone can achieve.

#### Acceptance Criteria

1. THE New_Project SHALL implement an agentic annotation module that accepts uncertain cluster labels and uses an LLM to suggest refined annotations with reasoning.
2. WHEN the Agentic_Annotation produces a suggestion, THE New_Project SHALL label the output as a suggestion (not authoritative) and require human approval before finalization.
3. THE New_Project SHALL log the model version, prompt context hash, and reasoning chain for every agentic annotation decision.
4. IF the LLM service is unavailable, THEN THE New_Project SHALL fall back to rule-based annotation without blocking the pipeline.

### Requirement 17: Annotation Low-Memory Mode and Marker Cache

**User Story:** As a computational biologist working with large datasets, I want annotation to support a low-memory execution mode and marker expression caching, so that annotation can run on resource-constrained environments.

#### Acceptance Criteria

1. WHERE low-memory mode is enabled, THE New_Project SHALL process annotation in chunked batches to limit peak memory usage.
2. THE New_Project SHALL implement a marker expression cache that stores precomputed marker scores to avoid redundant computation across annotation iterations.
3. WHEN the marker cache is populated, THE New_Project SHALL use cached scores for subsequent annotation runs on the same dataset version.

### Requirement 18: CCI Labels and Cell-Cell Interaction Analysis

**User Story:** As a computational biologist, I want cell-cell interaction (CCI) label assignment and ligand-receptor analysis with edge postprocessing, so that I can study intercellular communication patterns.

#### Acceptance Criteria

1. THE New_Project SHALL implement CCI label assignment that annotates cells with interaction-relevant labels based on ligand and receptor expression.
2. THE New_Project SHALL implement ligand-receptor analysis that identifies significant ligand-receptor pairs between cell type pairs.
3. THE New_Project SHALL implement LR edge postprocessing that filters, ranks, and annotates ligand-receptor edges with pathway context.
4. WHEN LR analysis completes, THE New_Project SHALL produce a structured output including interaction scores, p-values, and pathway annotations.

### Requirement 19: Analysis Modules Parity (Composition, DE Utils, Reporting)

**User Story:** As a computational biologist, I want composition analysis utilities, differential expression helper functions, pathway analysis, and automated reporting, so that I have the same analytical toolkit available in the new platform.

#### Acceptance Criteria

1. THE New_Project SHALL implement composition analysis utilities that compute cell type proportions, fold changes, and statistical comparisons across conditions.
2. THE New_Project SHALL implement DE utility functions that support volcano plots, gene ranking, and covariate-aware analysis.
3. THE New_Project SHALL implement a dedicated pathway analysis module that computes pathway activity scores using decoupler or equivalent backends.
4. THE New_Project SHALL implement an automated reporting module that generates QC reports, annotation summaries, and run diagnostic outputs.
5. THE New_Project SHALL implement annotation debug export that produces a diagnostic bundle for troubleshooting annotation issues.
6. THE New_Project SHALL implement an audit bundle generator that packages annotation QA metrics, calibration data, and provenance into a single reviewable artifact.

### Requirement 20: Myeloid Calibration and Subtyping Audit

**User Story:** As a bioinformatics lead, I want myeloid-specific calibration outputs and subtyping audit reports, so that I can validate myeloid cell classification accuracy.

#### Acceptance Criteria

1. THE New_Project SHALL implement myeloid calibration output generation that produces per-subtype confidence distributions and threshold recommendations.
2. THE New_Project SHALL implement a myeloid subtyping audit that compares assigned subtypes against reference panels and reports discrepancies.
3. WHEN a myeloid audit completes, THE New_Project SHALL produce a structured report with per-subtype precision, recall, and confusion metrics.

### Requirement 21: Other Stromal Resolution

**User Story:** As a bioinformatics lead, I want a dedicated module for resolving ambiguous stromal cell annotations, so that stromal subtypes (fibroblasts, pericytes, smooth muscle cells, endothelial subtypes) are accurately classified.

#### Acceptance Criteria

1. THE New_Project SHALL implement stromal resolution logic that disambiguates broad "Stromal" labels into specific subtypes using marker evidence and hierarchical rules.
2. WHEN stromal resolution completes, THE New_Project SHALL produce per-cell subtype labels with confidence scores and the marker evidence used for each assignment.

### Requirement 22: Zerna Label Index

**User Story:** As a computational biologist, I want a Zerna label index that provides a standardized lookup of cell type labels across ontologies and naming conventions, so that label harmonization is consistent.

#### Acceptance Criteria

1. THE New_Project SHALL implement a Zerna label index that maps cell type labels across Cell Ontology (CL), common aliases, and project-specific naming conventions.
2. WHEN a label lookup is performed, THE New_Project SHALL return the canonical label, ontology ID, aliases, and hierarchy path.

### Requirement 23: Programs Registry (Cancer-Type-Specific Workflows)

**User Story:** As a bioinformatics lead, I want a programs registry that defines cancer-type-specific analysis workflows (general, prostate, and future cancer types), so that the platform supports multi-cancer analysis with appropriate defaults.

#### Acceptance Criteria

1. THE New_Project SHALL implement a programs registry that catalogs cancer-type-specific analysis configurations including marker panels, hierarchy mappings, and default parameters.
2. THE New_Project SHALL include a general programs configuration that works across cancer types.
3. THE New_Project SHALL include a prostate-specific programs configuration with prostate-specific markers and hierarchy mappings.
4. WHEN a user selects a cancer program, THE New_Project SHALL apply the corresponding marker panels and analysis defaults to the pipeline.

### Requirement 24: Application Layer Parity (Plugin System, ML Foundation)

**User Story:** As a platform admin, I want a plugin system for extending the platform with custom analysis modules and an ML foundation layer for model management, so that the platform is extensible and AI-ready.

#### Acceptance Criteria

1. THE New_Project SHALL implement a plugin system that allows registration of custom analysis steps without modifying core platform code.
2. THE New_Project SHALL implement an ML foundation layer that manages model versioning, inference provenance, and model metadata storage.
3. WHEN a plugin is registered, THE New_Project SHALL validate the plugin's input/output contracts against the platform schema.
4. WHEN an ML model produces inference results, THE New_Project SHALL record the model version, input hash, and inference timestamp.

### Requirement 25: Presentation and UI View Parity

**User Story:** As a computational biologist, I want all analysis views from the original platform (cell communication, CellChat analysis, UMAP explorer, annotation log, upload multi-mode, evidence cards, obs schema inspector) available in the new platform, so that no analytical capability is lost.

#### Acceptance Criteria

1. THE New_Project SHALL implement a Cell Communication view that visualizes ligand-receptor interactions between cell types.
2. THE New_Project SHALL implement a CellChat Analysis view that displays CellChat-derived interaction networks and pathway enrichments.
3. THE New_Project SHALL implement a UMAP Explorer view with interactive pan, zoom, lasso selection, and metadata coloring.
4. THE New_Project SHALL implement an Annotation Log view that displays the chronological history of annotation changes with diffs.
5. THE New_Project SHALL implement an Evidence Card UI component that displays per-cluster annotation evidence (marker scores, reference mapping results, confidence).
6. THE New_Project SHALL implement an Obs Schema Inspector component that displays and validates the `.obs` DataFrame schema of loaded datasets.

### Requirement 26: Data Layer Parity (Zerna Connector, GPU Backend, Repository Pattern)

**User Story:** As a platform admin, I want a Zerna knowledge base data connector, a GPU compute backend abstraction, and a repository pattern for data access, so that the data layer is complete and hardware-flexible.

#### Acceptance Criteria

1. THE New_Project SHALL implement a Zerna data connector that queries the external Zerna knowledge base for marker genes, cell type definitions, and pathway annotations.
2. THE New_Project SHALL implement a GPU backend abstraction that allows compute steps to run on CPU or GPU with a unified interface.
3. THE New_Project SHALL implement a repository pattern for data access that abstracts storage operations (read, write, list, delete) behind a consistent interface.
4. WHEN GPU hardware is unavailable, THE New_Project SHALL fall back to CPU execution without requiring code changes.
