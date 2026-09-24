'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import type { Artifact, ArtifactType } from '@zerna/sdk';

const ARTIFACT_SORT_RANK: Partial<Record<ArtifactType, number>> = {
  h5ad: 0,
  de_results: 1,
  pathway_scores: 2,
  qc_report: 3,
};

function sortArtifactsForDisplay(artifacts: Artifact[]): Artifact[] {
  return [...artifacts].sort((a, b) => {
    const ra = ARTIFACT_SORT_RANK[a.artifact_type] ?? 100;
    const rb = ARTIFACT_SORT_RANK[b.artifact_type] ?? 100;
    if (ra !== rb) return ra - rb;
    return a.artifact_type.localeCompare(b.artifact_type);
  });
}

const ARTIFACT_LABELS: Record<string, string> = {
  h5ad: 'H5AD',
  embedding_plot: 'Embedding plot',
  qc_report: 'QC report',
  de_results: 'Differential expression',
  pathway_scores: 'Pathway scores',
  liana_results: 'Ligand-receptor',
};

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getArtifactDownloadHref(artifact: Artifact): string | null {
  if (!artifact.download_url) return null;
  return artifact.download_url.startsWith('/api/proxy') || !artifact.download_url.startsWith('/')
    ? artifact.download_url
    : `/api/proxy${artifact.download_url}`;
}

function getArtifactExploreHref(runId: string, artifact: Artifact): string | null {
  if (artifact.artifact_type === 'h5ad') return `/runs/${runId}/explore`;
  if (
    artifact.artifact_type === 'de_results' ||
    artifact.artifact_type === 'pathway_scores' ||
    artifact.artifact_type === 'liana_results'
  ) {
    return `/runs/${runId}/artifacts/${artifact.id}`;
  }
  return null;
}

function getArtifactExploreLabel(artifact: Artifact): string | null {
  if (artifact.artifact_type === 'h5ad') return 'Open explorer';
  if (
    artifact.artifact_type === 'de_results' ||
    artifact.artifact_type === 'pathway_scores' ||
    artifact.artifact_type === 'liana_results'
  ) {
    return 'Preview';
  }
  return null;
}

export default function RunArtifactList({
  runId,
  artifacts,
  emptyMessage,
}: {
  runId: string;
  artifacts: Artifact[];
  emptyMessage?: string;
}) {
  const sorted = useMemo(() => sortArtifactsForDisplay(artifacts), [artifacts]);

  return (
    <div className="card p-6">
      <h2 className="mb-2 text-sm font-semibold text-gray-800">Artifacts</h2>
      <p className="mb-4 text-sm text-gray-600">Open or download saved outputs from this run.</p>
      {sorted.length === 0 ? (
        <p className="text-sm text-gray-500">{emptyMessage ?? 'No artifacts available.'}</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {sorted.map((artifact) => (
            <li key={artifact.id} className="py-3 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <span className="text-sm font-medium text-gray-900">
                  {ARTIFACT_LABELS[artifact.artifact_type] ?? artifact.artifact_type}
                </span>
                <span className="ml-2 text-xs text-gray-400">
                  {formatBytes(artifact.size_bytes)}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-4">
                {getArtifactExploreHref(runId, artifact) && getArtifactExploreLabel(artifact) ? (
                  <Link
                    href={getArtifactExploreHref(runId, artifact)!}
                    className="text-sm text-gray-600 hover:text-gray-900 font-medium"
                  >
                    {getArtifactExploreLabel(artifact)}
                  </Link>
                ) : null}
                {getArtifactDownloadHref(artifact) ? (
                  <a
                    href={getArtifactDownloadHref(artifact)!}
                    download
                    className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                  >
                    Download
                  </a>
                ) : (
                  <span className="text-sm text-gray-400">Unavailable</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
