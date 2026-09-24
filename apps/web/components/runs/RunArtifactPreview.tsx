'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Artifact } from '@zerna/sdk';
import DEViewer, { type DEResult } from '@/components/analysis/DEViewer';
import LigandReceptorViewer from '@/components/analysis/LigandReceptorViewer';

interface ArtifactPreviewData {
  artifact_id: string;
  artifact_type: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number | null;
  truncated: boolean;
  metadata: Record<string, unknown>;
}

function formatValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—';
    if (Math.abs(value) >= 1000 || Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(3);
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function GenericTablePreview({
  columns,
  rows,
  maxRows = 25,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  maxRows?: number;
}) {
  return (
    <div className="card p-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-xs text-gray-500">
            {columns.map((column) => (
              <th key={column} className="pb-2 text-left font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {rows.slice(0, maxRows).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column} className="py-1.5 pr-4 align-top text-gray-700">
                  <span className="font-mono text-xs">{formatValue(row[column])}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <p className="mt-2 text-xs text-gray-400">
          Showing first {maxRows} rows from the loaded preview.
        </p>
      )}
    </div>
  );
}

export default function RunArtifactPreview({
  runId,
  artifact,
}: {
  runId: string;
  artifact: Artifact;
}) {
  const [data, setData] = useState<ArtifactPreviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadPreview() {
    try {
      setError(null);
      setLoading(true);
      const previewLimit = artifact.artifact_type === 'liana_results' ? 5000 : 200;
      const res = await fetch(
        `/api/proxy/v1/runs/${runId}/artifacts/${artifact.id}/preview?limit=${previewLimit}`
      );
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const payload = (await res.json()) as ArtifactPreviewData;
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load artifact preview');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPreview();
  }, [artifact.id, runId]);

  const deResults = useMemo<DEResult[]>(() => {
    if (artifact.artifact_type !== 'de_results' || !data) return [];
    return data.rows.map((row) => ({
      gene: String(row.gene ?? ''),
      cluster: String(row.cluster ?? ''),
      log_fold_change: Number(row.log_fold_change ?? 0),
      p_value: Number(row.p_value ?? 1),
      p_value_adj: Number(row.adjusted_p_value ?? row.p_value_adj ?? 1),
    }));
  }, [artifact.artifact_type, data]);

  const pathwayColumns = useMemo(() => {
    if (artifact.artifact_type !== 'pathway_scores' || !data) return [];
    return data.columns.filter((column) => column !== 'cell_id');
  }, [artifact.artifact_type, data]);

  const totalRowsLabel =
    data?.total_rows != null ? data.total_rows.toLocaleString() : `${data?.rows.length ?? 0}`;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard label="Artifact type" value={artifact.artifact_type} />
        <SummaryCard label="Rows" value={totalRowsLabel} />
        <SummaryCard
          label="Preview status"
          value={
            data?.truncated
              ? `Showing first ${data.rows.length.toLocaleString()} rows`
              : 'Full preview loaded'
          }
        />
      </div>

      {artifact.artifact_type === 'de_results' ? (
        <DEViewer
          results={deResults}
          isLoading={loading}
          error={error}
          onRetry={() => void loadPreview()}
        />
      ) : artifact.artifact_type === 'liana_results' ? (
        <LigandReceptorViewer
          columns={data?.columns ?? []}
          rows={data?.rows ?? []}
          isLoading={loading}
          error={error}
          onRetry={() => void loadPreview()}
          previewTruncated={data?.truncated ?? false}
          previewLoadedRowCount={data?.rows.length ?? null}
          previewTotalRows={data?.total_rows ?? null}
        />
      ) : loading ? (
        <div className="card p-6 text-sm text-gray-500">Loading artifact preview…</div>
      ) : error || !data ? (
        <div className="card p-6 text-sm text-red-600">{error ?? 'Preview unavailable.'}</div>
      ) : artifact.artifact_type === 'pathway_scores' ? (
        <div className="space-y-4">
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-gray-700">Pathway matrix preview</h2>
            <p className="mt-1 text-sm text-gray-500">
              This preview shows the saved per-cell pathway score matrix. Use download for full
              analysis externally when you need the full matrix.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {pathwayColumns.map((column) => (
                <span
                  key={column}
                  className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700"
                >
                  {column}
                </span>
              ))}
            </div>
          </div>
          <GenericTablePreview columns={data.columns} rows={data.rows} maxRows={20} />
        </div>
      ) : (
        <GenericTablePreview columns={data.columns} rows={data.rows} />
      )}
    </div>
  );
}
