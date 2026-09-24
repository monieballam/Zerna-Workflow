/**
 * Hand-authored TypeScript types that mirror the Zerna Pydantic schemas.
 *
 * These types are kept in sync with the OpenAPI spec and serve as the
 * primary type surface for SDK consumers until the generated schema is
 * available (i.e. before `pnpm generate` has been run).
 */

// ── Enums ─────────────────────────────────────────────────────────────────────

export type UserRole = 'admin' | 'member' | 'viewer';

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type ArtifactType =
  | 'h5ad'
  | 'embedding_plot'
  | 'qc_report'
  | 'de_results'
  | 'pathway_scores'
  | 'liana_results';

export type KnowledgePackType = 'cell_type_markers' | 'pathway_database' | 'ligand_receptor_pairs';

export type ExportType =
  | 'h5ad'
  | 'de_results'
  | 'embeddings'
  | 'report'
  | 'csv'
  | 'seurat'
  | 'plot_png'
  | 'plot_svg';

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface UserProfile {
  id: string;
  email: string;
  created_at: string;
  organizations: {
    organization_id: string;
    organization_name: string;
    role: UserRole;
    joined_at: string;
  }[];
  active_organization_id: string | null;
  active_organization_name: string | null;
  active_role: UserRole | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  organization_name?: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserProfile;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// ── Datasets ──────────────────────────────────────────────────────────────────

export interface DatasetVersionSummary {
  id: string;
  version: string;
  s3_path: string;
  cell_count: number | null;
  gene_count: number | null;
  file_format: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface Dataset {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  versions: DatasetVersionSummary[];
}

export interface CreateDatasetRequest {
  name: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateDatasetRequest {
  name?: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface ListDatasetsResponse {
  items: Dataset[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version: string;
  s3_path: string;
  cell_count: number | null;
  gene_count: number | null;
  file_format: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface DatasetVersionColumnsResponse {
  dataset_version_id: string;
  obs_columns: string[];
  batch_candidates: string[];
  cluster_candidates: string[];
  source: string;
}

export interface DeleteDatasetRequest {
  run_delete_mode?: 'preserve' | 'all' | 'selected';
  run_ids?: string[];
}

export interface DeleteDatasetResponse {
  dataset_id: string;
  deleted_runs: number;
  preserved_runs: number;
}

export interface BulkDeleteDatasetsRequest {
  scope: 'selected' | 'all';
  dataset_ids?: string[];
  run_delete_mode?: 'preserve' | 'all';
}

export interface BulkDeleteDatasetsResponse {
  scope: 'selected' | 'all';
  deleted_dataset_ids: string[];
  deleted_datasets: number;
  deleted_runs: number;
  preserved_runs: number;
}

// ── Feedback / Admin ─────────────────────────────────────────────────────────

export type FeedbackScope = 'system' | 'run';

export type FeedbackCategory = 'bug' | 'science' | 'ux' | 'performance' | 'feature' | 'other';

export interface CreateFeedbackRequest {
  scope?: FeedbackScope;
  category?: FeedbackCategory;
  run_id?: string;
  title?: string;
  message: string;
}

export interface Feedback {
  id: string;
  organization_id: string;
  user_id: string | null;
  user_email: string;
  scope: FeedbackScope;
  category: FeedbackCategory;
  title: string | null;
  message: string;
  run_id: string | null;
  dataset_id_snapshot: string | null;
  dataset_name_snapshot: string | null;
  template_id_snapshot: string | null;
  run_parameters_snapshot: Record<string, unknown> | null;
  run_status_snapshot: string | null;
  created_at: string;
}

export interface ListFeedbackResponse {
  items: Feedback[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface OrganizationMember {
  user_id: string;
  email: string;
  role: UserRole;
  joined_at: string;
  created_at: string;
}

export interface ListOrganizationMembersResponse {
  items: OrganizationMember[];
}

export interface CreateOrganizationMemberRequest {
  email: string;
  password?: string;
  role?: UserRole;
}

export interface UpdateOrganizationMemberRoleRequest {
  role: UserRole;
}

export type AdminFeedback = Feedback;

export interface ListAdminFeedbackResponse {
  items: AdminFeedback[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ── Runs ──────────────────────────────────────────────────────────────────────

export interface Run {
  id: string;
  organization_id: string;
  dataset_version_id: string | null;
  source_dataset_id: string | null;
  source_dataset_version_id: string | null;
  dataset_name: string | null;
  dataset_version_label: string | null;
  dataset_deleted: boolean;
  template_id: string;
  status: RunStatus;
  parameters: Record<string, unknown>;
  software_versions: Record<string, string> | null;
  random_seed: number | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface CreateRunRequest {
  dataset_version_id: string;
  template_id: string;
  parameters: Record<string, unknown>;
  random_seed?: number;
}

export interface ResumeRunRequest {
  parameters: Record<string, unknown>;
  random_seed?: number;
}

export interface DeleteRunResponse {
  run_id: string;
  deleted_artifacts: number;
  deleted_storage_objects: number;
}

export interface BulkDeleteRunsRequest {
  scope: 'failed' | 'all' | 'selected';
  dataset_id?: string;
  run_ids?: string[];
}

export interface BulkDeleteRunsResponse {
  scope: 'failed' | 'all' | 'selected';
  dataset_id: string | null;
  deleted_run_ids: string[];
  deleted_runs: number;
  deleted_artifacts: number;
  deleted_storage_objects: number;
}

export interface Artifact {
  id: string;
  run_id: string;
  artifact_type: ArtifactType;
  s3_path: string;
  size_bytes: number | null;
  metadata: Record<string, unknown>;
  download_url: string | null;
  created_at: string;
}

export interface ListRunsResponse {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ListArtifactsResponse {
  artifacts: Artifact[];
}

// ── Pipelines ─────────────────────────────────────────────────────────────────

export interface PipelineTemplate {
  id: string;
  organization_id: string;
  name: string;
  version: string;
  definition: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  /** Mirrors definition.metadata; omitted on older API responses (treat as false/true defaults). */
  deprecated?: boolean;
  /** When false, template is omitted from default GET /v1/pipelines lists (run picker). */
  visible_in_picker?: boolean;
  recommended?: boolean;
  template_family?: string | null;
}

export interface PipelineMethodCatalogEntry {
  name: string;
  label: string;
  description: string;
  order: number;
  default_selected: boolean;
  enabled_if: string | null;
}

export interface PipelineCatalogResponse {
  methods: PipelineMethodCatalogEntry[];
}

export interface CreatePipelineTemplateRequest {
  name: string;
  version: string;
  definition: Record<string, unknown>;
}

export interface ClonePipelineTemplateRequest {
  version: string;
  name?: string;
  definition?: Record<string, unknown>;
  deactivate_source?: boolean;
}

export type PipelineListResponse =
  | PipelineTemplate[]
  | {
      items: PipelineTemplate[];
      total: number;
    };

export interface ValidateParametersRequest {
  parameters: Record<string, unknown>;
}

export interface ValidateParametersResponse {
  valid: boolean;
  error: string | null;
}

// ── Annotations ───────────────────────────────────────────────────────────────

export interface AnnotationRevision {
  id: string;
  run_id: string;
  revision_number: number;
  annotations: Record<string, unknown>;
  knowledge_pack_id: string | null;
  method: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_by: string;
  created_at: string;
}

export interface CreateAnnotationRevisionRequest {
  annotations: Record<string, unknown>;
  method?: string;
  knowledge_pack_id?: string;
}

export interface EditAnnotationsRequest {
  edits: Record<string, unknown>;
}

export interface ListAnnotationRevisionsResponse {
  items: AnnotationRevision[];
  total: number;
}

// ── Knowledge Packs ───────────────────────────────────────────────────────────

export interface KnowledgePack {
  id: string;
  name: string;
  version: string;
  pack_type: KnowledgePackType;
  s3_path: string;
  schema_version: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface CreateKnowledgePackRequest {
  name: string;
  version: string;
  pack_type: KnowledgePackType;
  s3_path: string;
  schema_version?: string;
  metadata?: Record<string, unknown>;
}

export interface ListKnowledgePacksResponse {
  items: KnowledgePack[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ── Pathway Analysis ──────────────────────────────────────────────────────────

export interface PathwayPattern {
  pathway_name: string;
  pathway_id: string;
  datasets_present: string[];
  aggregated_score: number;
  p_value: number;
  confidence: number;
}

export interface CrossDatasetPathwayRequest {
  dataset_ids: string[];
  pathway_database?: string;
  aggregation_method?: string;
}

export interface CrossDatasetPathwayResponse {
  analysis_id: string;
  organization_id: string;
  dataset_ids: string[];
  pathway_database: string;
  aggregation_method: string;
  status: string;
  pathway_patterns: PathwayPattern[] | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface InterpretPathwayRequest {
  model?: string;
  context?: string;
}

export interface InterpretPathwayResponse {
  analysis_id: string;
  interpretation: string;
  hypotheses: string[];
  suggested_experiments: string[];
  model_used: string;
  cost_usd: number;
  from_cache: boolean;
}

export interface ListAnalysesResponse {
  items: CrossDatasetPathwayResponse[];
  total: number;
  page: number;
  page_size: number;
}

// ── Exports ───────────────────────────────────────────────────────────────────

export interface ExportRequest {
  export_type: ExportType;
}

export interface ExportResponse {
  run_id: string;
  export_type: ExportType;
  s3_path: string;
  status: string;
}

export interface ExportStatusResponse {
  run_id: string;
  available_exports: ExportType[];
}

export interface ExportDownloadResponse {
  run_id: string;
  export_type: ExportType;
  download_url: string;
  expires_in: number;
}

// ── Audit ─────────────────────────────────────────────────────────────────────

export interface AuditEvent {
  id: string;
  organization_id: string;
  user_id: string;
  action_type: string;
  resource_type: string;
  resource_id: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  timestamp: string;
}

export interface ListAuditEventsResponse {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ── Pagination helpers ────────────────────────────────────────────────────────

export interface PaginationParams {
  page?: number;
  page_size?: number;
  /** When true, list templates hidden from the run-creation picker (e.g. deprecated legacy seeds). */
  include_hidden_in_picker?: boolean;
}

// ── Error response ────────────────────────────────────────────────────────────

export interface ApiError {
  error_type: string;
  error_code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}
