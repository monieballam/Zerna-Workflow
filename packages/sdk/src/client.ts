/**
 * Zerna API client.
 *
 * A thin, fetch-based client that wraps every API endpoint with typed
 * request/response signatures.  Authentication tokens are managed
 * automatically — the client stores the access token in memory and
 * refreshes it transparently when it expires.
 *
 * @example
 * ```ts
 * import { ZernaClient } from "@zerna/sdk";
 *
 * const client = new ZernaClient({ baseUrl: "http://localhost:8000" });
 * await client.auth.login({ email: "user@example.com", password: "secret" });
 *
 * const datasets = await client.datasets.list({ page: 1, page_size: 20 });
 * ```
 */

import type {
  AnnotationRevision,
  ArtifactType,
  AuditEvent,
  CreateAnnotationRevisionRequest,
  CreateDatasetRequest,
  CreateKnowledgePackRequest,
  ClonePipelineTemplateRequest,
  CreatePipelineTemplateRequest,
  CreateRunRequest,
  DeleteRunResponse,
  BulkDeleteRunsRequest,
  BulkDeleteRunsResponse,
  BulkDeleteDatasetsRequest,
  BulkDeleteDatasetsResponse,
  CrossDatasetPathwayRequest,
  CrossDatasetPathwayResponse,
  CreateFeedbackRequest,
  CreateOrganizationMemberRequest,
  Dataset,
  DeleteDatasetRequest,
  DeleteDatasetResponse,
  DatasetVersionColumnsResponse,
  DatasetVersion,
  EditAnnotationsRequest,
  ExportDownloadResponse,
  ExportRequest,
  ExportResponse,
  ExportStatusResponse,
  ExportType,
  Feedback,
  InterpretPathwayRequest,
  InterpretPathwayResponse,
  KnowledgePack,
  KnowledgePackType,
  ListAdminFeedbackResponse,
  ListAnalysesResponse,
  ListAnnotationRevisionsResponse,
  ListArtifactsResponse,
  ListAuditEventsResponse,
  ListDatasetsResponse,
  ListFeedbackResponse,
  ListKnowledgePacksResponse,
  ListOrganizationMembersResponse,
  ListRunsResponse,
  LoginRequest,
  LoginResponse,
  OrganizationMember,
  PaginationParams,
  PipelineCatalogResponse,
  PipelineListResponse,
  PipelineTemplate,
  RefreshResponse,
  ResumeRunRequest,
  Run,
  RunStatus,
  SignupRequest,
  UserProfile,
  UpdateDatasetRequest,
  UpdateOrganizationMemberRoleRequest,
  ValidateParametersRequest,
  ValidateParametersResponse,
} from './types.js';

// ── Client configuration ──────────────────────────────────────────────────────

export interface ZernaClientConfig {
  /** Base URL of the Zerna API (no trailing slash). */
  baseUrl: string;
  /**
   * Optional initial access token.  If omitted, call `client.auth.login()`
   * before making authenticated requests.
   */
  accessToken?: string;
  /**
   * Optional refresh token (e.g. server-side cookies). Enables `client.auth.refresh()`.
   */
  refreshToken?: string;
  /** Fetch implementation (defaults to global `fetch`). */
  fetch?: typeof fetch;
}

// ── Internal helpers ──────────────────────────────────────────────────────────

class ApiResponseError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown
  ) {
    super(`Zerna API error ${status}`);
    this.name = 'ApiResponseError';
  }
}

function errorWithCause(message: string, cause: unknown): Error {
  const error = new Error(message) as Error & { cause?: unknown };
  error.cause = cause;
  return error;
}

// ── Sub-clients ───────────────────────────────────────────────────────────────

class AuthClient {
  constructor(private readonly http: HttpClient) {}

  /** Authenticate and store the returned tokens on the parent client. */
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const response = await this.http.post<LoginResponse>('/v1/auth/login', credentials, {
      skipAuth: true,
    });
    this.http.setAccessToken(response.access_token);
    this.http.setRefreshToken(response.refresh_token);
    return response;
  }

  /** Create a new account and store the returned tokens on the parent client. */
  async signup(data: SignupRequest): Promise<LoginResponse> {
    const response = await this.http.post<LoginResponse>('/v1/auth/signup', data, {
      skipAuth: true,
    });
    this.http.setAccessToken(response.access_token);
    this.http.setRefreshToken(response.refresh_token);
    return response;
  }

  /** Refresh the access token using the stored refresh token. */
  async refresh(): Promise<RefreshResponse> {
    const refreshToken = this.http.getRefreshToken();
    if (!refreshToken) throw new Error('No refresh token available');
    const response = await this.http.post<RefreshResponse>(
      '/v1/auth/refresh',
      { refresh_token: refreshToken },
      { skipAuth: true }
    );
    this.http.setAccessToken(response.access_token);
    this.http.setRefreshToken(response.refresh_token);
    return response;
  }

  /** Return the current authenticated user profile. */
  async me(): Promise<UserProfile> {
    return this.http.get<UserProfile>('/v1/auth/me');
  }

  /** Clear stored tokens (logout). */
  logout(): void {
    this.http.setAccessToken(null);
    this.http.setRefreshToken(null);
  }
}

class DatasetsClient {
  constructor(private readonly http: HttpClient) {}

  create(
    data: CreateDatasetRequest,
    files?: File[],
    opts?: { fileRelativePaths?: string[] }
  ): Promise<Dataset> {
    if (files && files.length > 0) {
      const form = new FormData();
      form.append('name', data.name);
      if (data.description) form.append('description', data.description);
      if (data.metadata) form.append('metadata', JSON.stringify(data.metadata));
      files.forEach((f) => form.append('files', f));
      if (opts?.fileRelativePaths?.length) {
        form.append('file_relative_paths', JSON.stringify(opts.fileRelativePaths));
      }
      return this.http.postForm<Dataset>('/v1/datasets', form);
    }
    return this.http.post<Dataset>('/v1/datasets', data);
  }

  list(
    params?: PaginationParams & {
      name?: string;
      file_format?: string;
    }
  ): Promise<ListDatasetsResponse> {
    return this.http.get<ListDatasetsResponse>('/v1/datasets', params);
  }

  get(id: string): Promise<Dataset> {
    return this.http.get<Dataset>(`/v1/datasets/${id}`);
  }

  getVersionColumns(id: string): Promise<DatasetVersionColumnsResponse> {
    return this.http.get<DatasetVersionColumnsResponse>(`/v1/datasets/versions/${id}/columns`);
  }

  update(id: string, data: UpdateDatasetRequest): Promise<Dataset> {
    return this.http.patch<Dataset>(`/v1/datasets/${id}`, data);
  }

  delete(id: string, data?: DeleteDatasetRequest): Promise<DeleteDatasetResponse> {
    return this.http.delete<DeleteDatasetResponse>(`/v1/datasets/${id}`, data);
  }

  bulkDelete(data: BulkDeleteDatasetsRequest): Promise<BulkDeleteDatasetsResponse> {
    return this.http.post<BulkDeleteDatasetsResponse>('/v1/datasets/bulk-delete', data);
  }

  createVersion(
    id: string,
    files: File[],
    opts?: { fileRelativePaths?: string[] }
  ): Promise<DatasetVersion> {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    if (opts?.fileRelativePaths?.length) {
      form.append('file_relative_paths', JSON.stringify(opts.fileRelativePaths));
    }
    return this.http.postForm<DatasetVersion>(`/v1/datasets/${id}/versions`, form);
  }
}

class RunsClient {
  constructor(private readonly http: HttpClient) {}

  create(data: CreateRunRequest): Promise<Run> {
    return this.http.post<Run>('/v1/runs', data);
  }

  list(
    params?: PaginationParams & {
      status?: RunStatus;
      dataset_version_id?: string;
      dataset_id?: string;
    }
  ): Promise<ListRunsResponse> {
    return this.http.get<ListRunsResponse>('/v1/runs', params);
  }

  get(id: string): Promise<Run> {
    return this.http.get<Run>(`/v1/runs/${id}`);
  }

  resume(id: string, data: ResumeRunRequest): Promise<Run> {
    return this.http.post<Run>(`/v1/runs/${id}/resume`, data);
  }

  cancel(id: string): Promise<void> {
    return this.http.post(`/v1/runs/${id}/cancel`, {});
  }

  delete(id: string): Promise<DeleteRunResponse> {
    return this.http.delete<DeleteRunResponse>(`/v1/runs/${id}`);
  }

  cleanup(data: BulkDeleteRunsRequest): Promise<BulkDeleteRunsResponse> {
    return this.http.post<BulkDeleteRunsResponse>('/v1/runs/cleanup', data);
  }

  listArtifacts(
    id: string,
    params?: { artifact_type?: ArtifactType }
  ): Promise<ListArtifactsResponse> {
    return this.http.get<ListArtifactsResponse>(`/v1/runs/${id}/artifacts`, params);
  }

  export(id: string, data: ExportRequest): Promise<ExportResponse> {
    return this.http.post<ExportResponse>(`/v1/runs/${id}/export`, data);
  }
}

class PipelinesClient {
  constructor(private readonly http: HttpClient) {}

  create(data: CreatePipelineTemplateRequest): Promise<PipelineTemplate> {
    return this.http.post<PipelineTemplate>('/v1/pipelines', data);
  }

  list(
    params?: PaginationParams & {
      name?: string;
      is_active?: boolean;
      include_hidden_in_picker?: boolean;
    }
  ): Promise<PipelineListResponse> {
    return this.http.get('/v1/pipelines', params);
  }

  get(id: string): Promise<PipelineTemplate> {
    return this.http.get<PipelineTemplate>(`/v1/pipelines/${id}`);
  }

  async getCatalog(): Promise<PipelineCatalogResponse> {
    try {
      return await this.http.get<PipelineCatalogResponse>('/v1/pipelines/catalog/methods');
    } catch (error) {
      if (error instanceof ApiResponseError && error.status === 404) {
        try {
          return await this.http.get<PipelineCatalogResponse>('/v1/pipelines/catalog');
        } catch (fallbackError) {
          if (fallbackError instanceof ApiResponseError && fallbackError.status === 422) {
            throw errorWithCause(
              'Pipeline catalog route collision detected. Restart the API server to load the latest pipeline routes.',
              fallbackError
            );
          }
          throw fallbackError;
        }
      }
      throw error;
    }
  }

  clone(id: string, data: ClonePipelineTemplateRequest): Promise<PipelineTemplate> {
    return this.http.post<PipelineTemplate>(`/v1/pipelines/${id}/clone`, data);
  }

  deactivate(id: string): Promise<PipelineTemplate> {
    return this.http.post<PipelineTemplate>(`/v1/pipelines/${id}/deactivate`, {});
  }

  async syncDefaults(): Promise<PipelineTemplate[]> {
    try {
      return await this.http.post<PipelineTemplate[]>('/v1/pipelines/catalog/sync-defaults', {});
    } catch (error) {
      if (error instanceof ApiResponseError && error.status === 404) {
        try {
          return await this.http.post<PipelineTemplate[]>('/v1/pipelines/sync-defaults', {});
        } catch (fallbackError) {
          if (fallbackError instanceof ApiResponseError && fallbackError.status === 422) {
            throw errorWithCause(
              'Pipeline sync route collision detected. Restart the API server to load the latest pipeline routes.',
              fallbackError
            );
          }
          throw fallbackError;
        }
      }
      throw error;
    }
  }

  validateParameters(
    id: string,
    data: ValidateParametersRequest
  ): Promise<ValidateParametersResponse> {
    return this.http.post<ValidateParametersResponse>(`/v1/pipelines/${id}/validate`, data);
  }
}

class AnnotationsClient {
  constructor(private readonly http: HttpClient) {}

  create(runId: string, data: CreateAnnotationRevisionRequest): Promise<AnnotationRevision> {
    return this.http.post<AnnotationRevision>(`/v1/runs/${runId}/annotations`, data);
  }

  list(runId: string): Promise<ListAnnotationRevisionsResponse> {
    return this.http.get<ListAnnotationRevisionsResponse>(`/v1/runs/${runId}/annotations`);
  }

  edit(id: string, data: EditAnnotationsRequest): Promise<AnnotationRevision> {
    return this.http.patch<AnnotationRevision>(`/v1/annotations/${id}`, data);
  }

  approve(id: string): Promise<AnnotationRevision> {
    return this.http.post<AnnotationRevision>(`/v1/annotations/${id}/approve`, {});
  }
}

class KnowledgePacksClient {
  constructor(private readonly http: HttpClient) {}

  create(data: CreateKnowledgePackRequest): Promise<KnowledgePack> {
    return this.http.post<KnowledgePack>('/v1/knowledge-packs', data);
  }

  list(
    params?: PaginationParams & {
      pack_type?: KnowledgePackType;
    }
  ): Promise<ListKnowledgePacksResponse> {
    return this.http.get<ListKnowledgePacksResponse>('/v1/knowledge-packs', params);
  }

  get(id: string): Promise<KnowledgePack> {
    return this.http.get<KnowledgePack>(`/v1/knowledge-packs/${id}`);
  }
}

class PathwayClient {
  constructor(private readonly http: HttpClient) {}

  analyzeCrossDataset(data: CrossDatasetPathwayRequest): Promise<CrossDatasetPathwayResponse> {
    return this.http.post<CrossDatasetPathwayResponse>('/v1/pathway/cross-dataset', data);
  }

  getAnalysis(id: string): Promise<CrossDatasetPathwayResponse> {
    return this.http.get<CrossDatasetPathwayResponse>(`/v1/pathway/analyses/${id}`);
  }

  listAnalyses(params?: PaginationParams): Promise<ListAnalysesResponse> {
    return this.http.get<ListAnalysesResponse>('/v1/pathway/analyses', params);
  }

  interpret(id: string, data: InterpretPathwayRequest): Promise<InterpretPathwayResponse> {
    return this.http.post<InterpretPathwayResponse>(`/v1/pathway/${id}/interpret`, data);
  }
}

class ExportsClient {
  constructor(private readonly http: HttpClient) {}

  getStatus(runId: string): Promise<ExportStatusResponse> {
    return this.http.get<ExportStatusResponse>(`/v1/exports/${runId}/status`);
  }

  getDownloadUrl(runId: string, exportType: ExportType): Promise<ExportDownloadResponse> {
    return this.http.get<ExportDownloadResponse>(`/v1/exports/${runId}/download`, {
      export_type: exportType,
    });
  }
}

class AuditClient {
  constructor(private readonly http: HttpClient) {}

  list(
    params?: PaginationParams & {
      resource_type?: string;
      action_type?: string;
    }
  ): Promise<ListAuditEventsResponse> {
    return this.http.get<ListAuditEventsResponse>('/v1/audit', params);
  }

  get(id: string): Promise<AuditEvent> {
    return this.http.get<AuditEvent>(`/v1/audit/${id}`);
  }
}

class FeedbackClient {
  constructor(private readonly http: HttpClient) {}

  create(data: CreateFeedbackRequest): Promise<Feedback> {
    return this.http.post<Feedback>('/v1/feedback', data);
  }

  list(
    params?: PaginationParams & {
      scope?: string;
      category?: string;
    }
  ): Promise<ListFeedbackResponse> {
    return this.http.get<ListFeedbackResponse>('/v1/feedback', params);
  }
}

class AdminClient {
  constructor(private readonly http: HttpClient) {}

  listMembers(): Promise<ListOrganizationMembersResponse> {
    return this.http.get<ListOrganizationMembersResponse>('/v1/admin/members');
  }

  createMember(data: CreateOrganizationMemberRequest): Promise<OrganizationMember> {
    return this.http.post<OrganizationMember>('/v1/admin/members', data);
  }

  updateMemberRole(
    id: string,
    data: UpdateOrganizationMemberRoleRequest
  ): Promise<OrganizationMember> {
    return this.http.patch<OrganizationMember>(`/v1/admin/members/${id}`, data);
  }

  listFeedback(
    params?: PaginationParams & {
      scope?: string;
      category?: string;
    }
  ): Promise<ListAdminFeedbackResponse> {
    return this.http.get<ListAdminFeedbackResponse>('/v1/admin/feedback', params);
  }
}

// ── Core HTTP client ──────────────────────────────────────────────────────────

class HttpClient {
  private accessToken: string | null;
  private refreshToken: string | null;
  private readonly fetchFn: typeof fetch;

  constructor(
    private readonly baseUrl: string,
    config: ZernaClientConfig
  ) {
    this.accessToken = config.accessToken ?? null;
    this.refreshToken = config.refreshToken ?? null;
    this.fetchFn = config.fetch ?? globalThis.fetch;
  }

  setAccessToken(token: string | null): void {
    this.accessToken = token;
  }

  setRefreshToken(token: string | null): void {
    this.refreshToken = token;
  }

  getRefreshToken(): string | null {
    return this.refreshToken;
  }

  private buildUrl(path: string, params?: Record<string, unknown>): string {
    const url = new URL(path, this.baseUrl);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, this.serializeQueryValue(value));
        }
      }
    }
    return url.toString();
  }

  private serializeQueryValue(value: unknown): string {
    if (
      typeof value === 'string' ||
      typeof value === 'number' ||
      typeof value === 'boolean' ||
      typeof value === 'bigint'
    ) {
      return String(value);
    }
    if (value instanceof Date) {
      return value.toISOString();
    }
    return JSON.stringify(value);
  }

  private headers(skipAuth = false): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json' };
    if (!skipAuth && this.accessToken) {
      h['Authorization'] = `Bearer ${this.accessToken}`;
    }
    return h;
  }

  private async handleResponse<T>(res: Response): Promise<T> {
    // Read the body once only — a failed res.json() still consumes the stream, so
    // falling back to res.text() causes "Body has already been read" (seen on login errors).
    const text = await res.text();

    if (!res.ok) {
      let body: unknown = text;
      const trimmed = text.trim();
      if (trimmed) {
        try {
          body = JSON.parse(text) as unknown;
        } catch {
          body = text;
        }
      }
      throw new ApiResponseError(res.status, body);
    }

    if (res.status === 204 || text.length === 0) {
      return undefined as T;
    }
    return JSON.parse(text) as T;
  }

  async get<T>(path: string, params?: object): Promise<T> {
    const res = await this.fetchFn(
      this.buildUrl(path, params as Record<string, unknown> | undefined),
      {
        method: 'GET',
        headers: this.headers(),
      }
    );
    return this.handleResponse<T>(res);
  }

  async post<T>(path: string, body: unknown, opts?: { skipAuth?: boolean }): Promise<T> {
    const res = await this.fetchFn(this.buildUrl(path), {
      method: 'POST',
      headers: this.headers(opts?.skipAuth),
      body: JSON.stringify(body),
    });
    return this.handleResponse<T>(res);
  }

  async postForm<T>(path: string, form: FormData): Promise<T> {
    const headers: Record<string, string> = {};
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }
    const res = await this.fetchFn(this.buildUrl(path), {
      method: 'POST',
      headers,
      body: form,
    });
    return this.handleResponse<T>(res);
  }

  async patch<T>(path: string, body: unknown): Promise<T> {
    const res = await this.fetchFn(this.buildUrl(path), {
      method: 'PATCH',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    return this.handleResponse<T>(res);
  }

  async delete<T = void>(path: string, body?: unknown): Promise<T> {
    const res = await this.fetchFn(this.buildUrl(path), {
      method: 'DELETE',
      headers: this.headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return this.handleResponse<T>(res);
  }
}

// ── Public client ─────────────────────────────────────────────────────────────

/**
 * Zerna API client.
 *
 * @example
 * ```ts
 * const client = new ZernaClient({ baseUrl: "http://localhost:8000" });
 * await client.auth.login({ email: "user@example.com", password: "secret" });
 * const { items } = await client.datasets.list();
 * ```
 */
export class ZernaClient {
  readonly auth: AuthClient;
  readonly datasets: DatasetsClient;
  readonly runs: RunsClient;
  readonly pipelines: PipelinesClient;
  readonly annotations: AnnotationsClient;
  readonly knowledgePacks: KnowledgePacksClient;
  readonly pathway: PathwayClient;
  readonly exports: ExportsClient;
  readonly audit: AuditClient;
  readonly feedback: FeedbackClient;
  readonly admin: AdminClient;

  constructor(config: ZernaClientConfig) {
    const http = new HttpClient(config.baseUrl, config);
    this.auth = new AuthClient(http);
    this.datasets = new DatasetsClient(http);
    this.runs = new RunsClient(http);
    this.pipelines = new PipelinesClient(http);
    this.annotations = new AnnotationsClient(http);
    this.knowledgePacks = new KnowledgePacksClient(http);
    this.pathway = new PathwayClient(http);
    this.exports = new ExportsClient(http);
    this.audit = new AuditClient(http);
    this.feedback = new FeedbackClient(http);
    this.admin = new AdminClient(http);
  }
}

export { ApiResponseError };
