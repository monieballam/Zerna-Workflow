/**
 * @zerna/sdk — TypeScript SDK for the Zerna Control Plane API.
 *
 * @example
 * ```ts
 * import { ZernaClient } from "@zerna/sdk";
 *
 * const client = new ZernaClient({ baseUrl: "http://localhost:8000" });
 * await client.auth.login({ email: "user@example.com", password: "secret" });
 * ```
 */

export { ZernaClient, ApiResponseError } from './client';
export type { ZernaClientConfig } from './client';

// All hand-authored types
export type {
  // Enums
  UserRole,
  RunStatus,
  ArtifactType,
  KnowledgePackType,
  ExportType,
  // Auth
  UserProfile,
  LoginRequest,
  SignupRequest,
  LoginResponse,
  RefreshRequest,
  RefreshResponse,
  FeedbackScope,
  FeedbackCategory,
  CreateFeedbackRequest,
  Feedback,
  ListFeedbackResponse,
  OrganizationMember,
  ListOrganizationMembersResponse,
  CreateOrganizationMemberRequest,
  UpdateOrganizationMemberRoleRequest,
  AdminFeedback,
  ListAdminFeedbackResponse,
  // Datasets
  DatasetVersionSummary,
  Dataset,
  CreateDatasetRequest,
  UpdateDatasetRequest,
  ListDatasetsResponse,
  DatasetVersion,
  DatasetVersionColumnsResponse,
  DeleteDatasetRequest,
  DeleteDatasetResponse,
  BulkDeleteDatasetsRequest,
  BulkDeleteDatasetsResponse,
  // Runs
  Run,
  CreateRunRequest,
  ResumeRunRequest,
  Artifact,
  ListRunsResponse,
  ListArtifactsResponse,
  DeleteRunResponse,
  BulkDeleteRunsRequest,
  BulkDeleteRunsResponse,
  // Pipelines
  PipelineTemplate,
  PipelineMethodCatalogEntry,
  PipelineCatalogResponse,
  CreatePipelineTemplateRequest,
  ClonePipelineTemplateRequest,
  PipelineListResponse,
  ValidateParametersRequest,
  ValidateParametersResponse,
  // Annotations
  AnnotationRevision,
  CreateAnnotationRevisionRequest,
  EditAnnotationsRequest,
  ListAnnotationRevisionsResponse,
  // Knowledge Packs
  KnowledgePack,
  CreateKnowledgePackRequest,
  ListKnowledgePacksResponse,
  // Pathway
  PathwayPattern,
  CrossDatasetPathwayRequest,
  CrossDatasetPathwayResponse,
  InterpretPathwayRequest,
  InterpretPathwayResponse,
  ListAnalysesResponse,
  // Exports
  ExportRequest,
  ExportResponse,
  ExportStatusResponse,
  ExportDownloadResponse,
  // Audit
  AuditEvent,
  ListAuditEventsResponse,
  // Helpers
  PaginationParams,
  ApiError,
} from './types';
