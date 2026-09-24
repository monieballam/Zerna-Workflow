# Tasks: Gap Analysis and Verification

## Phase 1: Data Ingestion & Binding (Requirements 1, 3, 8)

- [x] 1. Implement Upload Service
  - [x] 1.1 Create `apps/api/services/upload_service.py` with multipart file upload accepting h5ad, 10x mtx, 10x h5, csv, tsv formats and persisting to S3
  - [x] 1.2 Add S3 URI registration mode (`s3://` path import without browser upload)
  - [x] 1.3 Create upload API route in `apps/api/routes/uploads.py` with multipart endpoint
  - [x] 1.4 Write property test for file format acceptance (Property 1)

- [x] 2. Implement Merge Validator
  - [x] 2.1 Create `apps/api/services/merge_validator.py` with schema compatibility checking and conflict reporting
  - [x] 2.2 Write property test for merge validation and conflict detection (Property 2)

- [x] 3. Implement Dataset Versioning
  - [x] 3.1 Extend `apps/api/services/dataset_service.py` with immutable version creation including checksum, lineage, schema summary
  - [x] 3.2 Add Alembic migration for dataset version lineage fields (parent_version_ids, source_type, schema_summary)
  - [x] 3.3 Write property test for dataset version immutability and lineage completeness (Property 3)

- [x] 4. Implement Run Binding Enforcement
  - [x] 4.1 Extend `apps/api/services/run_service.py` to require `dataset_version_id` in run start contract and record checksum in manifest
  - [x] 4.2 Update `apps/api/schemas/run.py` to add `dataset_version_id` as required field
  - [x] 4.3 Write property test for run start dataset version binding (Property 6)

- [x] 5. Replace Stub Backends with Persistent Storage
  - [x] 5.1 Replace in-memory project listings with database-backed CRUD in `apps/api/services/`
  - [x] 5.2 Replace in-memory DAG definitions with database-backed storage with version history
  - [x] 5.3 Replace static run comparison data with persisted run artifacts and metrics
  - [x] 5.4 Write property test for persistent storage CRUD round-trip (Property 11)

## Phase 2: Compute Plane Parity (Requirements 2, 17, 26)

- [x] 6. Implement Real Pipeline Compute
  - [x] 6.1 Wire pipeline DAG steps to real scientific backends (Scanpy, scVI, scDblFinder) in `methods/` modules
  - [x] 6.2 Implement checkpoint persistence on step failure in `workflows/run_execution/`
  - [x] 6.3 Write property test for step output schema conformance (Property 4)
  - [x] 6.4 Write property test for checkpoint persistence on failure (Property 5)

- [x] 7. Implement Run Replay and Reproducibility
  - [x] 7.1 Implement run manifest persistence and replay logic in `apps/api/services/run_service.py`
  - [x] 7.2 Write property test for deterministic method replay reproducibility (Property 7)
  - [x] 7.3 Write property test for run persistence round-trip (Property 8)

- [x] 8. Implement Data Layer Components
  - [x] 8.1 Create `methods/data/repository.py` with abstract storage interface (read, write, list, delete)
  - [x] 8.2 Complete GPU backend abstraction fallback paths in `services/gpu_abstraction/`
  - [x] 8.3 Create `methods/data/zerna_connector.py` for external knowledge base queries
  - [x] 8.4 Write property test for repository pattern round-trip (Property 50)
  - [x] 8.5 Write property test for GPU/CPU execution equivalence and fallback (Property 49)

## Phase 3: Annotation Domain — Gating & Hierarchy (Requirements 10, 11, 12)

- [x] 9. Implement Deterministic Gating Module
  - [x] 9.1 Create `methods/annotation/deterministic_gating.py` with marker threshold classification from YAML/JSON panels
  - [x] 9.2 Implement hierarchy mapping (general L1/L2/L3, myeloid-specific, stromal-specific v1/v2)
  - [x] 9.3 Write property test for gating classification correctness (Property 13)
  - [x] 9.4 Write property test for hierarchy mapping consistency (Property 14)
  - [x] 9.5 Write property test for gating provenance completeness (Property 15)

- [x] 10. Implement Annotation Guardrails
  - [x] 10.1 Create `methods/annotation/guardrails.py` with ontology and hierarchy constraint validation
  - [x] 10.2 Implement label normalization (variant strings to canonical names)
  - [x] 10.3 Implement annotation columns policy (required, optional, protected columns)
  - [x] 10.4 Write property test for guardrail violation detection (Property 16)
  - [x] 10.5 Write property test for label normalization idempotence (Property 17)
  - [x] 10.6 Write property test for annotation columns policy enforcement (Property 18)

- [x] 11. Implement Label Lifecycle Manager
  - [x] 11.1 Create `methods/annotation/label_lifecycle.py` with label contract, validation, finalize, and post-finalize guard
  - [x] 11.2 Write property test for guardrail-blocked finalization (Property 19)
  - [x] 11.3 Write property test for label contract validation completeness (Property 20)
  - [x] 11.4 Write property test for finalization locks labels (Property 21)
  - [x] 11.5 Write property test for post-finalize modification guard (Property 22)

## Phase 4: Annotation Domain — Scoring, Evaluation, Agentic (Requirements 13–16)

- [x] 12. Implement Annotation Scoring and Utilities
  - [x] 12.1 Create `methods/annotation/scoring.py` with per-cluster and per-cell confidence scoring
  - [x] 12.2 Implement marker pack loader and taxonomy loader
  - [x] 12.3 Implement subtype assignment logic
  - [x] 12.4 Implement annotation robustness layer (perturbation testing)
  - [x] 12.5 Write property test for annotation confidence score bounds (Property 23)
  - [x] 12.6 Write property test for marker pack and taxonomy loader round-trip (Property 24)
  - [x] 12.7 Write property test for subtype refinement hierarchy consistency (Property 25)
  - [x] 12.8 Write property test for annotation robustness under perturbation (Property 26)

- [x] 13. Implement Annotation Evaluation and Provenance
  - [x] 13.1 Create `methods/annotation/evaluation.py` with L1/L2/L3 layer consistency evaluation
  - [x] 13.2 Implement marker provenance tracking (source, version, citation)
  - [x] 13.3 Write property test for annotation layer consistency (Property 27)
  - [x] 13.4 Write property test for marker provenance tracking completeness (Property 28)

- [x] 14. Implement Evidence Scoring and Marker Index
  - [x] 14.1 Create `methods/annotation/evidence_scoring.py` with composite confidence scoring
  - [x] 14.2 Implement marker index loader and search
  - [x] 14.3 Write property test for evidence scoring composite bounds (Property 29)
  - [x] 14.4 Write property test for marker index completeness and search (Property 30)

- [x] 15. Implement Agentic Annotation
  - [x] 15.1 Create `methods/annotation/agentic.py` with LLM-assisted label refinement
  - [x] 15.2 Implement rule-based fallback when LLM is unavailable
  - [x] 15.3 Write property test for agentic suggestion metadata invariants (Property 31)
  - [x] 15.4 Write property test for LLM fallback to rule-based annotation (Property 32)

## Phase 5: Annotation Domain — Low-Memory, CCI, Specialized (Requirements 17–22)

- [x] 16. Implement Low-Memory Mode and Marker Cache
  - [x] 16.1 Create `methods/annotation/lowmem.py` with chunked batch processing
  - [x] 16.2 Create `methods/annotation/marker_cache.py` with precomputed score caching
  - [x] 16.3 Write property test for low-memory mode equivalence (Property 33)
  - [x] 16.4 Write property test for marker cache round-trip (Property 34)

- [x] 17. Implement CCI Labels and LR Analysis
  - [x] 17.1 Create `methods/annotation/cci_labels.py` with CCI label assignment and LR analysis
  - [x] 17.2 Implement LR edge postprocessing (filter, rank, pathway annotation)
  - [x] 17.3 Write property test for CCI label assignment (Property 35)
  - [x] 17.4 Write property test for LR analysis output completeness and ranking (Property 36)

- [x] 18. Implement Myeloid Audit
  - [x] 18.1 Create `methods/annotation/myeloid_audit.py` with calibration output and subtyping audit
  - [x] 18.2 Write property test for myeloid calibration output structure (Property 40)
  - [x] 18.3 Write property test for myeloid audit report structure (Property 41)

- [x] 19. Implement Stromal Resolution
  - [x] 19.1 Create `methods/annotation/stromal_resolution.py` with subtype disambiguation
  - [x] 19.2 Write property test for stromal resolution (Property 42)

- [x] 20. Implement Zerna Label Index
  - [x] 20.1 Create `methods/annotation/zerna_index.py` with cross-ontology label mapping
  - [x] 20.2 Write property test for Zerna label index lookup completeness (Property 43)

## Phase 6: Analysis & Reporting (Requirements 19, 23)

- [x] 21. Implement Analysis Modules
  - [x] 21.1 Create `methods/analysis/composition.py` with cell type proportion and fold change computation
  - [x] 21.2 Create `methods/analysis/de_utils.py` with volcano plot data and gene ranking utilities
  - [x] 21.3 Create `methods/analysis/pathway.py` with pathway activity scoring
  - [x] 21.4 Write property test for composition proportions sum to one (Property 37)
  - [x] 21.5 Write property test for DE utility volcano data completeness (Property 38)

- [x] 22. Implement Reporting and Audit Bundles
  - [x] 22.1 Create `methods/analysis/reporting.py` with QC report, annotation summary, and diagnostic generation
  - [x] 22.2 Implement annotation debug export and audit bundle generator
  - [x] 22.3 Write property test for report and audit bundle completeness (Property 39)

- [x] 23. Implement Programs Registry
  - [x] 23.1 Create `methods/programs/registry.py` with cancer-type-specific configuration catalog
  - [x] 23.2 Add general and prostate-specific program configurations
  - [x] 23.3 Write property test for programs registry round-trip (Property 44)
  - [x] 23.4 Write property test for program selection applies correct defaults (Property 45)

## Phase 7: Analyst UX (Requirements 4–7, 9, 25)

- [x] 24. Implement Explorer and Atlas Views
  - [x] 24.1 Create `apps/web/components/embedding/EmbeddingExplorer.tsx` with filter, gene overlay, color-by, split-view
  - [x] 24.2 Create `apps/web/components/analysis/CellTypeAtlas.tsx` with marker tables, confidence, expression plots
  - [x] 24.3 Create `apps/web/app/(dashboard)/overview/page.tsx` with dataset stats and run status summary

- [x] 25. Implement Run History and Replay UI
  - [x] 25.1 Create `apps/web/components/runs/RunHistory.tsx` with searchable list, load, and replay
  - [x] 25.2 Add Previous Runs page at `apps/web/app/(dashboard)/runs/history/page.tsx`

- [x] 26. Implement Export Center
  - [x] 26.1 Extend `apps/web/components/analysis/ExportCenter.tsx` with h5ad/csv/Seurat export and reproducibility report
  - [x] 26.2 Add PNG/SVG plot export support
  - [x] 26.3 Write property test for export format support and reproducibility report completeness (Property 9)

- [x] 27. Implement Interpreter Page
  - [x] 27.1 Create `apps/web/app/(dashboard)/interpreter/page.tsx` with NL query interface
  - [x] 27.2 Create `apps/api/services/interpreter_service.py` with query parsing and session history
  - [x] 27.3 Write property test for query session history persistence (Property 10)

- [x] 28. Implement Annotation Workflow Auto-Wiring
  - [x] 28.1 Extend annotation workflow to auto-consume cluster results from completed runs
  - [x] 28.2 Maintain manual JSON override in advanced mode
  - [x] 28.3 Write property test for annotation workflow auto-wiring (Property 12)

- [x] 29. Implement Remaining UI Views
  - [x] 29.1 Create `apps/web/components/analysis/CellCommunication.tsx` for LR interaction visualization
  - [x] 29.2 Create `apps/web/components/analysis/CellChatAnalysis.tsx` for CellChat networks
  - [x] 29.3 Create `apps/web/components/annotation/AnnotationLog.tsx` for annotation change history
  - [x] 29.4 Create `apps/web/components/annotation/EvidenceCard.tsx` for per-cluster evidence display
  - [x] 29.5 Create `apps/web/components/datasets/ObsSchemaInspector.tsx` for .obs schema validation
  - [x] 29.6 Write property test for obs schema validation (Property 48)

## Phase 8: Platform Extension (Requirement 24)

- [x] 30. Implement Plugin System
  - [x] 30.1 Create `apps/api/services/plugin_service.py` with plugin registration and contract validation
  - [x] 30.2 Write property test for plugin registration and contract validation (Property 46)

- [x] 31. Implement ML Foundation Layer
  - [x] 31.1 Create `apps/api/services/ml_foundation_service.py` with model versioning and inference provenance
  - [x] 31.2 Write property test for ML inference provenance logging (Property 47)
