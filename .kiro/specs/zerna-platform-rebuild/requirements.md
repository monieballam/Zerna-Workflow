# Requirements Document

## Introduction

Zerna is a multi-user, cloud-native single-cell analysis platform for cancer research. This document specifies requirements for rebuilding Zerna from scratch to preserve critical product behavior from the POC while establishing a production-ready architecture. The rebuild separates control plane (metadata, orchestration) from compute plane (scientific methods), eliminates monolithic UI-driven workflows, and implements proper observability and multi-tenancy from day one.

## Glossary

- **Control_Plane**: The subsystem managing authentication, projects, datasets, manifests, and API orchestration
- **Compute_Plane**: The subsystem executing scientific methods and batch jobs
- **Orchestration_Layer**: The component within Compute_Plane responsible for workload scheduling and resource allocation
- **Dataset**: A collection of single-cell expression data files uploaded by users
- **DatasetVersion**: An immutable snapshot of a Dataset with specific file contents
- **Run**: An execution instance of a PipelineTemplate against a DatasetVersion
- **Artifact**: An output file or object produced by a Run (h5ad, plots, reports)
- **PipelineTemplate**: A reusable definition of a scientific workflow with configurable parameters
- **MethodDefinition**: A specification of a single scientific operation (QC, normalization, clustering, etc.)
- **KnowledgePack**: A versioned collection of reference data (cell type markers, pathway databases)
- **AnnotationRevision**: A versioned cell type annotation with confidence scores and provenance
- **AuditEvent**: An immutable record of user actions for compliance and reproducibility
- **Temporal**: The workflow orchestration engine for product-level workflows
- **Nextflow**: The DAG execution engine for scientific pipelines
- **h5ad**: AnnData HDF5 format for single-cell data
- **Embedding**: A 2D/3D projection of high-dimensional cell data (UMAP, t-SNE)
- **HVG**: Highly Variable Genes used for dimensionality reduction
- **DE**: Differential Expression analysis between cell populations
- **Batch_Correction**: Methods to remove technical variation between datasets

## Requirements

### Requirement 1: User Authentication and Authorization

**User Story:** As a platform user, I want secure authentication and role-based access control, so that my research data remains private and properly governed.

#### Acceptance Criteria

1. THE Control_Plane SHALL authenticate users via OAuth2 with JWT tokens
2. THE Control_Plane SHALL support organization-level user management with roles (admin, member, viewer)
3. WHEN a user attempts to access a resource, THE Control_Plane SHALL verify the user has appropriate permissions
4. THE Control_Plane SHALL enforce project-level access control where users can only access projects they are members of
5. THE Control_Plane SHALL log all authentication attempts as AuditEvents

### Requirement 2: Dataset Upload and Ingestion

**User Story:** As an analyst scientist, I want to upload single-cell data files in multiple formats, so that I can analyze data from different sequencing platforms.

#### Acceptance Criteria

1. WHEN a user uploads files, THE Control_Plane SHALL accept h5ad, 10x h5, 10x mtx, csv, and tsv formats
2. WHEN multiple files are uploaded, THE Control_Plane SHALL support merging them into a single Dataset
3. THE Control_Plane SHALL validate file formats and return descriptive errors for invalid files
4. WHEN a Dataset is created, THE Control_Plane SHALL generate a unique DatasetVersion identifier
5. THE Control_Plane SHALL store uploaded files in S3 with organization-scoped paths
6. THE Control_Plane SHALL record Dataset metadata (cell count, gene count, upload timestamp) in PostgreSQL
7. WHEN a Dataset upload completes, THE Control_Plane SHALL emit an event to trigger downstream processing

### Requirement 3: Pipeline Template Management

**User Story:** As a computational biologist, I want to define reusable pipeline templates with configurable parameters, so that I can standardize analysis workflows across projects.

#### Acceptance Criteria

1. THE Control_Plane SHALL store PipelineTemplate definitions with versioning
2. THE Control_Plane SHALL validate PipelineTemplate schemas against MethodDefinition contracts
3. WHEN a PipelineTemplate is created, THE Control_Plane SHALL ensure all referenced MethodDefinitions exist
4. THE Control_Plane SHALL support parameter overrides at Run creation time
5. THE Control_Plane SHALL maintain immutable PipelineTemplate versions for reproducibility

### Requirement 4: Scientific Pipeline Execution

**User Story:** As an analyst scientist, I want to execute scientific pipelines on my datasets, so that I can perform QC, clustering, and annotation.

#### Acceptance Criteria

1. WHEN a user initiates a Run, THE Control_Plane SHALL create a Temporal workflow
2. THE Temporal workflow SHALL translate the PipelineTemplate into a Nextflow DAG
3. THE Compute_Plane SHALL execute MethodDefinitions in dependency order
4. THE Compute_Plane SHALL implement QC filtering (cell count, gene count, mitochondrial percentage thresholds)
5. THE Compute_Plane SHALL implement doublet detection using scrublet or similar methods
6. THE Compute_Plane SHALL implement normalization (log1p, scaling) using scanpy
7. THE Compute_Plane SHALL implement HVG selection with configurable gene count
8. THE Compute_Plane SHALL implement PCA dimensionality reduction
9. THE Compute_Plane SHALL implement clustering (Leiden, Louvain) with configurable resolution
10. THE Compute_Plane SHALL implement embedding generation (UMAP, t-SNE)
11. THE Compute_Plane SHALL implement batch correction (Harmony, scVI) when multiple batches are detected
12. THE Compute_Plane SHALL implement differential expression analysis between clusters
13. THE Compute_Plane SHALL implement pathway scoring using decoupler
14. THE Compute_Plane SHALL implement ligand-receptor analysis using LIANA
15. WHEN a MethodDefinition completes, THE Compute_Plane SHALL store outputs as Artifacts in S3
16. WHEN a MethodDefinition fails, THE Compute_Plane SHALL capture error details and halt the Run
17. THE Compute_Plane SHALL emit progress events to the Control_Plane for UI updates

### Requirement 5: Cell Type Annotation

**User Story:** As a computational biologist, I want to annotate cell clusters with hierarchical cell types and confidence scores, so that I can identify cell populations accurately.

#### Acceptance Criteria

1. THE Compute_Plane SHALL integrate CellTypist for automated cell type prediction
2. WHEN annotation is performed, THE Compute_Plane SHALL generate confidence scores per cell
3. THE Control_Plane SHALL store AnnotationRevisions with hierarchical labels (tissue → lineage → cell_type)
4. THE Control_Plane SHALL track annotation provenance (method, KnowledgePack version, user edits)
5. WHEN a user manually edits annotations, THE Control_Plane SHALL create a new AnnotationRevision
6. THE Control_Plane SHALL support annotation approval workflows for reviewer/lead personas

### Requirement 6: Knowledge Pack Management

**User Story:** As a platform admin, I want to manage versioned reference datasets, so that annotations remain reproducible as knowledge evolves.

#### Acceptance Criteria

1. THE Control_Plane SHALL store KnowledgePacks with semantic versioning
2. THE Control_Plane SHALL support KnowledgePack types (cell_type_markers, pathway_databases, ligand_receptor_pairs)
3. WHEN a KnowledgePack is updated, THE Control_Plane SHALL preserve previous versions
4. THE Control_Plane SHALL associate each AnnotationRevision with a specific KnowledgePack version
5. THE Control_Plane SHALL validate KnowledgePack schemas before storage

### Requirement 7: Run Lifecycle Management

**User Story:** As an analyst scientist, I want to browse previous runs and their outputs, so that I can compare results and track analysis history.

#### Acceptance Criteria

1. THE Control_Plane SHALL list all Runs for a Dataset with status (queued, running, completed, failed)
2. THE Control_Plane SHALL display Run metadata (start time, duration, parameter values)
3. WHEN a Run completes, THE Control_Plane SHALL mark all Artifacts as available
4. THE Control_Plane SHALL support Run cancellation with cleanup of partial Artifacts
5. THE Control_Plane SHALL retain Run history indefinitely for audit purposes

### Requirement 8: Interactive Data Exploration

**User Story:** As an analyst scientist, I want to explore embeddings and cell metadata interactively, so that I can understand my data visually.

#### Acceptance Criteria

1. THE Web_App SHALL display an overview dashboard with dataset statistics
2. THE Web_App SHALL render 2D embeddings with cell coloring by metadata (cluster, cell_type, gene_expression)
3. WHEN a user selects cells in an embedding, THE Web_App SHALL display selected cell metadata
4. THE Web_App SHALL support zooming and panning on embeddings
5. THE Web_App SHALL display cluster-level statistics (cell count, top marker genes)
6. THE Web_App SHALL support side-by-side comparison of multiple Runs

### Requirement 9: Data Export and Interoperability

**User Story:** As a computational biologist, I want to export analysis results in standard formats, so that I can use external tools for further analysis.

#### Acceptance Criteria

1. WHEN a user requests export, THE Control_Plane SHALL generate h5ad files with all annotations and embeddings
2. THE Control_Plane SHALL support export of differential expression results as CSV
3. THE Control_Plane SHALL support export of embeddings as CSV with cell metadata
4. THE Control_Plane SHALL generate reproducibility reports in HTML format
5. THE Control_Plane SHALL include pipeline parameters and software versions in reproducibility reports

### Requirement 10: Observability and Monitoring

**User Story:** As a platform admin, I want comprehensive observability, so that I can diagnose issues and optimize performance.

#### Acceptance Criteria

1. THE Control_Plane SHALL emit OpenTelemetry traces for all API requests
2. THE Compute_Plane SHALL emit OpenTelemetry traces for all MethodDefinition executions
3. THE Control_Plane SHALL emit metrics for Run duration, Artifact size, and API latency
4. THE Control_Plane SHALL log all errors with structured context (user_id, project_id, run_id)
5. THE Control_Plane SHALL integrate with distributed tracing backends (Jaeger, Tempo)

### Requirement 11: Multi-Tenancy and Resource Isolation

**User Story:** As a platform admin, I want strict resource isolation between organizations, so that data leakage is prevented.

#### Acceptance Criteria

1. THE Control_Plane SHALL scope all database queries by organization_id
2. THE Control_Plane SHALL store S3 artifacts with organization-prefixed paths
3. THE Control_Plane SHALL enforce storage quotas per organization
4. THE Control_Plane SHALL enforce compute quotas (concurrent Runs) per organization
5. WHEN a user queries resources, THE Control_Plane SHALL return only resources within their organization

### Requirement 12: API Contract Enforcement

**User Story:** As a frontend developer, I want strongly-typed API contracts, so that integration errors are caught at compile time.

#### Acceptance Criteria

1. THE API SHALL define all request and response schemas using Pydantic v2
2. THE API SHALL generate OpenAPI specifications automatically
3. THE SDK SHALL provide TypeScript types generated from OpenAPI specifications
4. THE API SHALL validate all incoming requests against schemas and return 422 for violations
5. THE API SHALL version endpoints with URL prefixes (e.g., /v1/datasets)

### Requirement 13: Workflow Orchestration Separation

**User Story:** As a platform engineer, I want product workflows separated from scientific DAGs, so that orchestration concerns are properly isolated.

#### Acceptance Criteria

1. THE Control_Plane SHALL use Temporal for product workflows (dataset ingestion, run lifecycle, export)
2. THE Compute_Plane SHALL use Nextflow for scientific DAG execution
3. THE Temporal workflows SHALL communicate with Nextflow via API calls, not direct process invocation
4. THE Temporal workflows SHALL handle retries and compensation logic for product operations
5. THE Nextflow pipelines SHALL be idempotent and resumable

### Requirement 14: Configuration Management

**User Story:** As a platform engineer, I want externalized configuration, so that deployments are environment-agnostic.

#### Acceptance Criteria

1. THE Control_Plane SHALL load configuration from environment variables
2. THE Control_Plane SHALL support configuration profiles (development, staging, production)
3. THE Control_Plane SHALL validate required configuration at startup and fail fast if missing
4. THE Control_Plane SHALL not hardcode database credentials, API keys, or S3 paths
5. THE Control_Plane SHALL support secret injection from external secret managers

### Requirement 15: Audit Trail and Compliance

**User Story:** As a compliance officer, I want immutable audit logs, so that all user actions are traceable for regulatory purposes.

#### Acceptance Criteria

1. THE Control_Plane SHALL record AuditEvents for all data mutations (create, update, delete)
2. THE Control_Plane SHALL record AuditEvents for all Run executions
3. THE Control_Plane SHALL record AuditEvents for all annotation approvals
4. THE AuditEvent SHALL include timestamp, user_id, action_type, resource_id, and before/after state
5. THE Control_Plane SHALL prevent deletion or modification of AuditEvents

### Requirement 16: Error Handling and User Feedback

**User Story:** As an analyst scientist, I want clear error messages when pipelines fail, so that I can correct issues and re-run analyses.

#### Acceptance Criteria

1. WHEN a MethodDefinition fails, THE Compute_Plane SHALL capture stdout, stderr, and exit code
2. WHEN a Run fails, THE Control_Plane SHALL display the failing MethodDefinition and error message in the UI
3. THE Control_Plane SHALL categorize errors (user_error, system_error, transient_error)
4. WHEN a transient error occurs, THE Temporal workflow SHALL retry with exponential backoff
5. WHEN a user error occurs, THE Control_Plane SHALL not retry and SHALL prompt user action

### Requirement 17: Performance and Scalability

**User Story:** As a platform admin, I want the platform to handle large datasets and concurrent users, so that performance remains acceptable under load.

#### Acceptance Criteria

1. THE Control_Plane SHALL handle datasets with up to 1 million cells
2. THE Control_Plane SHALL support at least 100 concurrent users per organization
3. THE Control_Plane SHALL cache frequently accessed metadata in Redis
4. THE Control_Plane SHALL paginate API responses with configurable page size
5. THE Compute_Plane SHALL support horizontal scaling of MethodDefinition workers

### Requirement 18: Monorepo Structure and Code Organization

**User Story:** As a platform engineer, I want a well-organized monorepo, so that code is discoverable and dependencies are explicit.

#### Acceptance Criteria

1. THE Repository SHALL organize code into apps (web, api, orchestrator), packages (contracts, sdk), services, methods, and workflows directories
2. THE Repository SHALL define shared contracts in the packages/contracts directory
3. THE Repository SHALL generate SDK clients from contracts in the packages/sdk directory
4. THE Repository SHALL isolate MethodDefinitions in the methods directory with no cross-method imports
5. THE Repository SHALL define Temporal workflows in the workflows directory
6. THE Repository SHALL define Nextflow pipelines in the services/compute directory

### Requirement 19: Testing and Quality Assurance

**User Story:** As a platform engineer, I want comprehensive automated tests, so that regressions are caught before production.

#### Acceptance Criteria

1. THE Repository SHALL include unit tests for all MethodDefinitions with property-based testing for scientific correctness
2. THE Repository SHALL include integration tests for API endpoints
3. THE Repository SHALL include end-to-end tests for critical user workflows (upload → run → explore)
4. THE Repository SHALL enforce minimum code coverage thresholds (80% for business logic)
5. THE Repository SHALL run tests in CI on every pull request

### Requirement 20: Documentation and Developer Experience

**User Story:** As a new developer, I want comprehensive documentation, so that I can contribute to the platform quickly.

#### Acceptance Criteria

1. THE Repository SHALL include a README with setup instructions
2. THE Repository SHALL include architecture diagrams for Control_Plane and Compute_Plane
3. THE Repository SHALL include API documentation generated from OpenAPI specifications
4. THE Repository SHALL include MethodDefinition documentation with input/output schemas
5. THE Repository SHALL include runbooks for common operational tasks (deployment, rollback, debugging)

### Requirement 21: Disease-Agnostic Design

**User Story:** As a platform engineer, I want the platform to be disease-agnostic, so that it can support research beyond cancer.

#### Acceptance Criteria

1. THE Control_Plane SHALL not include disease-specific logic in core services
2. THE Control_Plane SHALL support custom metadata fields per Dataset
3. THE Control_Plane SHALL allow KnowledgePacks to be scoped by research domain
4. THE MethodDefinitions SHALL operate on generic single-cell data without disease assumptions
5. THE Web_App SHALL not hardcode disease-specific terminology in UI labels

### Requirement 22: Recommendation and ML Integration

**User Story:** As an ML/AI engineer, I want to integrate recommendation services, so that users receive intelligent suggestions for pipeline parameters.

#### Acceptance Criteria

1. THE Control_Plane SHALL expose webhook endpoints for external recommendation services
2. WHEN a Dataset is uploaded, THE Control_Plane SHALL optionally call recommendation services for parameter suggestions
3. THE Control_Plane SHALL display recommendations in the UI with confidence scores
4. THE Control_Plane SHALL allow users to accept or reject recommendations
5. THE Control_Plane SHALL log recommendation acceptance rates as metrics

### Requirement 23: Batch Correction and Multi-Sample Analysis

**User Story:** As a computational biologist, I want to correct batch effects when analyzing multiple samples, so that biological signal is not confounded by technical variation.

#### Acceptance Criteria

1. WHEN a Dataset contains multiple batches, THE Compute_Plane SHALL detect batch keys from metadata
2. THE Compute_Plane SHALL apply batch correction methods (Harmony, scVI, Combat) based on PipelineTemplate configuration
3. THE Compute_Plane SHALL generate before/after batch correction embeddings for visual comparison
4. THE Compute_Plane SHALL compute batch correction quality metrics (kBET, LISI)
5. THE Compute_Plane SHALL store batch correction parameters in Run metadata for reproducibility

### Requirement 24: Differential Expression Analysis

**User Story:** As a computational biologist, I want to identify marker genes for each cluster, so that I can characterize cell populations.

#### Acceptance Criteria

1. WHEN a Run includes clustering, THE Compute_Plane SHALL perform differential expression analysis between all cluster pairs
2. THE Compute_Plane SHALL compute log fold change, p-values, and adjusted p-values for each gene
3. THE Compute_Plane SHALL rank genes by statistical significance and effect size
4. THE Compute_Plane SHALL store DE results as Artifacts in CSV format
5. THE Web_App SHALL display top marker genes per cluster in the UI

### Requirement 25: Pathway and Gene Set Enrichment

**User Story:** As a computational biologist, I want to score cells by pathway activity and discover cross-dataset pathway patterns, so that I can interpret biological functions and identify novel biological insights.

#### Acceptance Criteria

1. THE Compute_Plane SHALL integrate decoupler for pathway scoring
2. THE Compute_Plane SHALL support multiple pathway databases (MSigDB, GO, KEGG) via KnowledgePacks
3. WHEN pathway scoring is performed, THE Compute_Plane SHALL generate per-cell pathway scores
4. THE Compute_Plane SHALL store pathway scores in the h5ad Artifact
5. THE Web_App SHALL allow coloring embeddings by pathway scores
6. THE Control_Plane SHALL support cross-dataset pathway analysis that aggregates patterns across multiple researcher datasets
7. WHEN cross-dataset analysis is requested, THE Compute_Plane SHALL identify pathway patterns that span multiple datasets
8. THE Control_Plane SHALL support post-pipeline pathway analysis that can execute independently from initial pipeline runs
9. WHERE LLM integration is configured, THE Control_Plane SHALL provide pathway interpretation and hypothesis generation via GPT or Claude APIs
10. THE Control_Plane SHALL cross-reference pathway patterns across datasets to discover novel biological insights not visible in single datasets

### Requirement 26: Ligand-Receptor Interaction Analysis

**User Story:** As a computational biologist, I want to identify cell-cell communication patterns, so that I can understand tissue microenvironment interactions.

#### Acceptance Criteria

1. THE Compute_Plane SHALL integrate LIANA for ligand-receptor analysis
2. THE Compute_Plane SHALL compute interaction scores between all cluster pairs
3. THE Compute_Plane SHALL rank interactions by statistical significance
4. THE Compute_Plane SHALL store interaction results as Artifacts in CSV format
5. THE Web_App SHALL visualize interaction networks with cluster nodes and weighted edges

### Requirement 27: Reproducibility and Provenance

**User Story:** As a computational biologist, I want complete provenance tracking, so that I can reproduce analyses and satisfy publication requirements.

#### Acceptance Criteria

1. THE Control_Plane SHALL record software versions (scanpy, scvi-tools, CellTypist) for each Run
2. THE Control_Plane SHALL record random seeds used in stochastic MethodDefinitions
3. THE Control_Plane SHALL record KnowledgePack versions used in annotations
4. THE Control_Plane SHALL generate reproducibility reports with all provenance information
5. FOR ALL Runs, re-executing with identical parameters and software versions SHALL produce equivalent results

### Requirement 28: UI Component Modularity

**User Story:** As a frontend developer, I want modular UI components with no business logic, so that the UI remains maintainable.

#### Acceptance Criteria

1. THE Web_App SHALL implement presentational components with props-only interfaces
2. THE Web_App SHALL delegate all business logic to API calls
3. THE Web_App SHALL not exceed 500 lines per component file
4. THE Web_App SHALL use React Server Components for data fetching where applicable
5. THE Web_App SHALL implement loading and error states for all async operations

### Requirement 29: API Rate Limiting and Throttling

**User Story:** As a platform admin, I want API rate limiting, so that individual users cannot degrade platform performance.

#### Acceptance Criteria

1. THE Control_Plane SHALL enforce rate limits per user (e.g., 100 requests per minute)
2. WHEN a user exceeds rate limits, THE Control_Plane SHALL return HTTP 429 with retry-after header
3. THE Control_Plane SHALL implement token bucket or sliding window rate limiting
4. THE Control_Plane SHALL exempt platform admins from rate limits
5. THE Control_Plane SHALL expose rate limit metrics for monitoring

### Requirement 30: Heterogeneous Compute Resource Utilization

**User Story:** As a platform engineer, I want to utilize all available processing power including heterogeneous GPUs, so that computational workloads execute efficiently across diverse hardware.

#### Acceptance Criteria

1. THE Compute_Plane SHALL detect and utilize all available CPU and GPU resources at runtime
2. THE Compute_Plane SHALL support NVIDIA GPUs via CUDA
3. THE Compute_Plane SHALL support AMD GPUs via ROCm
4. THE Compute_Plane SHALL support Apple Silicon GPUs via Metal
5. THE Compute_Plane SHALL support Intel GPUs
6. THE Compute_Plane SHALL support Google TPUs
7. WHEN a MethodDefinition is executed, THE Compute_Plane SHALL automatically detect available compute resources
8. THE Compute_Plane SHALL allow MethodDefinitions to specify compute preferences (CPU-only, GPU-preferred, GPU-required)
9. WHEN multiple compute resources are available, THE Orchestration_Layer SHALL distribute workloads based on hardware availability and method requirements
10. THE Compute_Plane SHALL optimize workload scheduling to maximize utilization of heterogeneous hardware
