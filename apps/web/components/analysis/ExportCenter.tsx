'use client';

import { useState, useTransition } from 'react';
import type { ExportType, ExportStatusResponse } from '@zerna/sdk';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ExportCenterProps {
  runId: string;
  exportStatus: ExportStatusResponse | null;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onRequestExport: (runId: string, exportType: ExportType) => Promise<{ error?: string }>;
  onGetDownloadUrl: (
    runId: string,
    exportType: ExportType
  ) => Promise<{ url?: string; error?: string }>;
}

// ── Config ────────────────────────────────────────────────────────────────────

const EXPORT_FORMATS: {
  type: ExportType;
  label: string;
  description: string;
  icon: string;
  category: 'data' | 'plot' | 'report';
}[] = [
  {
    type: 'h5ad',
    label: 'H5AD',
    description: 'AnnData HDF5 file with all annotations, embeddings, and metadata',
    icon: '🧬',
    category: 'data',
  },
  {
    type: 'csv',
    label: 'CSV',
    description: 'Cell metadata and annotations as a flat CSV table',
    icon: '📋',
    category: 'data',
  },
  {
    type: 'seurat',
    label: 'Seurat bundle',
    description: 'Seurat-compatible RDS bundle with counts, metadata, and reductions',
    icon: '🔬',
    category: 'data',
  },
  {
    type: 'de_results',
    label: 'DE results (CSV)',
    description: 'Differential expression results with log fold change and p-values',
    icon: '📊',
    category: 'data',
  },
  {
    type: 'embeddings',
    label: 'Embeddings (CSV)',
    description: 'UMAP/t-SNE coordinates with cell metadata',
    icon: '📐',
    category: 'data',
  },
  {
    type: 'plot_png',
    label: 'Plots (PNG)',
    description: 'All visualization outputs as high-resolution PNG images',
    icon: '🖼️',
    category: 'plot',
  },
  {
    type: 'plot_svg',
    label: 'Plots (SVG)',
    description: 'All visualization outputs as scalable SVG vector graphics',
    icon: '🎨',
    category: 'plot',
  },
  {
    type: 'report',
    label: 'Reproducibility report',
    description: 'HTML report with run manifest, parameter provenance, and method versions',
    icon: '📄',
    category: 'report',
  },
];

// ── Export card ───────────────────────────────────────────────────────────────

interface ExportCardProps {
  runId: string;
  type: ExportType;
  label: string;
  description: string;
  icon: string;
  category: 'data' | 'plot' | 'report';
  available: boolean;
  onRequestExport: ExportCenterProps['onRequestExport'];
  onGetDownloadUrl: ExportCenterProps['onGetDownloadUrl'];
}

function ExportCard({
  runId,
  type,
  label,
  description,
  icon,
  available,
  onRequestExport,
  onGetDownloadUrl,
}: ExportCardProps) {
  const [isPending, startTransition] = useTransition();
  const [exportError, setExportError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  function handleExport() {
    setExportError(null);
    startTransition(async () => {
      const result = await onRequestExport(runId, type);
      if (result.error) {
        setExportError(result.error);
      } else {
        setIsGenerating(true);
      }
    });
  }

  function handleDownload() {
    startTransition(async () => {
      const result = await onGetDownloadUrl(runId, type);
      if (result.error) {
        setExportError(result.error);
      } else if (result.url) {
        setDownloadUrl(result.url);
        window.open(result.url, '_blank', 'noopener,noreferrer');
      }
    });
  }

  return (
    <div
      className={`card p-4 flex items-start gap-4 ${available ? '' : 'opacity-60'}`}
      data-testid={`export-card-${type}`}
    >
      <span className="text-2xl shrink-0" aria-hidden="true">
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
          {available && (
            <span
              className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
              data-testid={`available-badge-${type}`}
            >
              Available
            </span>
          )}
          {isGenerating && !available && (
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
              Generating…
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-3">{description}</p>

        {exportError && (
          <p className="text-xs text-red-600 mb-2" data-testid={`export-error-${type}`}>
            {exportError}
          </p>
        )}

        <div className="flex gap-2">
          {available ? (
            <button
              onClick={handleDownload}
              disabled={isPending}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid={`download-btn-${type}`}
            >
              {isPending ? 'Preparing…' : 'Download'}
            </button>
          ) : (
            <button
              onClick={handleExport}
              disabled={isPending || isGenerating}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid={`generate-btn-${type}`}
            >
              {isPending ? 'Requesting…' : isGenerating ? 'Generating…' : 'Generate'}
            </button>
          )}
          {downloadUrl && (
            <a
              href={downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              data-testid={`direct-link-${type}`}
            >
              Open link
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Reproducibility report preview ───────────────────────────────────────────

interface ReportPreviewProps {
  runId: string;
  softwareVersions?: Record<string, string>;
  randomSeed?: number | null;
  parameters?: Record<string, unknown>;
}

function ReportPreview({ runId, softwareVersions, randomSeed, parameters }: ReportPreviewProps) {
  return (
    <div className="card p-4 mt-4" data-testid="report-preview">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Reproducibility report preview</h2>
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">Run ID</dt>
          <dd className="font-mono text-gray-900">{runId}</dd>
        </div>
        {randomSeed != null && (
          <div>
            <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">Random seed</dt>
            <dd className="font-mono text-gray-900">{randomSeed}</dd>
          </div>
        )}
        {softwareVersions && Object.keys(softwareVersions).length > 0 && (
          <div>
            <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">
              Software versions
            </dt>
            <dd>
              <ul className="space-y-0.5">
                {Object.entries(softwareVersions).map(([pkg, ver]) => (
                  <li key={pkg} className="font-mono text-gray-700 text-xs">
                    {pkg}: {ver}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        {parameters && Object.keys(parameters).length > 0 && (
          <div>
            <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">Parameters</dt>
            <dd>
              <ul className="space-y-0.5">
                {Object.entries(parameters).map(([k, v]) => (
                  <li key={k} className="font-mono text-gray-700 text-xs">
                    {k}: {JSON.stringify(v)}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface ExportCenterFullProps extends ExportCenterProps {
  softwareVersions?: Record<string, string>;
  randomSeed?: number | null;
  parameters?: Record<string, unknown>;
}

export default function ExportCenter({
  runId,
  exportStatus,
  isLoading = false,
  error = null,
  onRetry,
  onRequestExport,
  onGetDownloadUrl,
  softwareVersions,
  randomSeed,
  parameters,
}: ExportCenterFullProps) {
  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="export-center-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading export status…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="export-center-error"
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-sm text-red-600">{error}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  const available = new Set(exportStatus?.available_exports ?? []);

  const dataFormats = EXPORT_FORMATS.filter((f) => f.category === 'data');
  const plotFormats = EXPORT_FORMATS.filter((f) => f.category === 'plot');
  const reportFormats = EXPORT_FORMATS.filter((f) => f.category === 'report');

  return (
    <div className="space-y-6" data-testid="export-center">
      <p className="text-sm text-gray-500">
        Generate and download analysis results in standard formats.
      </p>

      {/* Data exports */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
          Data exports
        </h2>
        <div className="space-y-3">
          {dataFormats.map((fmt) => (
            <ExportCard
              key={fmt.type}
              runId={runId}
              type={fmt.type}
              label={fmt.label}
              description={fmt.description}
              icon={fmt.icon}
              category={fmt.category}
              available={available.has(fmt.type)}
              onRequestExport={onRequestExport}
              onGetDownloadUrl={onGetDownloadUrl}
            />
          ))}
        </div>
      </section>

      {/* Plot exports */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
          Plot exports
        </h2>
        <div className="space-y-3">
          {plotFormats.map((fmt) => (
            <ExportCard
              key={fmt.type}
              runId={runId}
              type={fmt.type}
              label={fmt.label}
              description={fmt.description}
              icon={fmt.icon}
              category={fmt.category}
              available={available.has(fmt.type)}
              onRequestExport={onRequestExport}
              onGetDownloadUrl={onGetDownloadUrl}
            />
          ))}
        </div>
      </section>

      {/* Reproducibility report */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
          Reproducibility
        </h2>
        <div className="space-y-3">
          {reportFormats.map((fmt) => (
            <ExportCard
              key={fmt.type}
              runId={runId}
              type={fmt.type}
              label={fmt.label}
              description={fmt.description}
              icon={fmt.icon}
              category={fmt.category}
              available={available.has(fmt.type)}
              onRequestExport={onRequestExport}
              onGetDownloadUrl={onGetDownloadUrl}
            />
          ))}
        </div>
      </section>

      <ReportPreview
        runId={runId}
        softwareVersions={softwareVersions}
        randomSeed={randomSeed}
        parameters={parameters}
      />
    </div>
  );
}
