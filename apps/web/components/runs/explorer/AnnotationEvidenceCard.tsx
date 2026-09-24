'use client';

import type { ReactNode } from 'react';
import {
  filterNoiseGenesForDisplay,
  rankDistinctiveMarkers,
  subtractGenes,
} from '@/lib/marker-evidence-utils';
import ClusterAliasEditor from './ClusterAliasEditor';
import ContradictionEvidencePanel from './ContradictionEvidencePanel';
import type { ClusterInspectorSummary } from './cluster-inspector-types';
import MarkerEvidenceList from './MarkerEvidenceList';

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h4 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">{children}</h4>
  );
}

export default function AnnotationEvidenceCard({
  cluster,
  displayAlias,
  onAliasSave,
  geneOverlayGene,
  onGeneClick,
  technicalIdKind = 'cluster',
}: {
  cluster: ClusterInspectorSummary;
  displayAlias: string;
  onAliasSave: (clusterId: string, alias: string) => void;
  geneOverlayGene: string | null;
  onGeneClick: (gene: string) => void;
  technicalIdKind?: 'cluster' | 'lineage_partition' | 'fine_partition';
}) {
  const supportRaw = cluster.annotation_support_markers ?? [];
  const topMarkersRaw = cluster.top_markers ?? [];
  const supportDisplay = filterNoiseGenesForDisplay(supportRaw, { maxOut: 50 });
  const topMarkersFiltered = filterNoiseGenesForDisplay(topMarkersRaw, { maxOut: 200 });
  const hasPipelineSupport = supportRaw.length > 0;
  const supportSet = new Set(supportDisplay.map((g) => g.trim()));
  const withoutSupport = subtractGenes(topMarkersFiltered, supportSet);
  const distinctivePool = withoutSupport.length > 0 ? withoutSupport : topMarkersFiltered;
  const distinctive = rankDistinctiveMarkers(distinctivePool, 40);
  const overlapsPipelineSupportMarkers =
    hasPipelineSupport && distinctive.length > 0 && distinctive.every((g) => supportSet.has(g));
  const fallbackMarkersDisplay = filterNoiseGenesForDisplay(topMarkersRaw.slice(0, 80), {
    maxOut: 8,
  });
  const supportHiddenByFilter =
    hasPipelineSupport && supportRaw.length > 0 && supportDisplay.length === 0;

  const runnerUps = cluster.runner_up_labels ?? [];
  const hasContradictionContent =
    runnerUps.length > 0 || Boolean(cluster.conservative_reason || cluster.conservative_status);

  return (
    <div
      className="rounded-lg border border-gray-200 bg-gray-50/40 p-3"
      data-testid="annotation-evidence-card"
    >
      <p className="text-xs font-semibold text-gray-800">Annotation evidence</p>

      <div className="mt-3 space-y-4">
        <div>
          <SectionTitle>Identity</SectionTitle>
          <dl className="mt-1.5 space-y-1 text-[11px] text-gray-700">
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-gray-500">
                {technicalIdKind === 'lineage_partition' || technicalIdKind === 'fine_partition'
                  ? 'Partition ID'
                  : 'Technical ID'}
              </dt>
              <dd className="font-mono text-gray-900">{cluster.cluster_id}</dd>
            </div>
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-gray-500">Pipeline / saved label</dt>
              <dd className="font-medium text-gray-900" data-testid="evidence-pipeline-saved-label">
                {cluster.label}
              </dd>
            </div>
            {displayAlias ? (
              <div className="flex flex-wrap gap-x-2">
                <dt className="text-gray-500">Technical display alias</dt>
                <dd className="font-medium text-blue-900" data-testid="evidence-technical-alias">
                  {displayAlias}
                </dd>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-gray-500">Confidence</dt>
              <dd className="capitalize">{cluster.confidence.replace(/_/g, ' ')}</dd>
            </div>
          </dl>
        </div>

        <div>
          <SectionTitle>Support for pipeline / saved label</SectionTitle>
          {hasPipelineSupport ? (
            <div className="mt-1.5 space-y-1">
              <p className="text-[11px] text-gray-600">
                Annotation pipeline support markers
                {cluster.annotation_mode ? (
                  <>
                    {' '}
                    (<span className="font-mono text-gray-700">{cluster.annotation_mode}</span>)
                  </>
                ) : null}
                {cluster.annotation_support_source_label ? (
                  <>
                    {' '}
                    · Support markers keyed on:{' '}
                    <span className="font-medium">{cluster.annotation_support_source_label}</span>
                  </>
                ) : null}
                {cluster.retrieval_tiebreak_applied ? (
                  <span className="text-gray-500"> · retrieval prior tie-break applied</span>
                ) : null}
                {cluster.annotation_support_partition_de_overlap &&
                cluster.annotation_support_source_label ? (
                  <span className="mt-1 block text-[10px] leading-snug text-slate-600">
                    Genes listed here are the overlap between partition-level DE markers and the
                    pack row above — not the full pack list alone.
                  </span>
                ) : null}
                {cluster.annotation_support_source_label &&
                cluster.annotation_support_aligned_with_primary_headline === false ? (
                  <span className="mt-1 block text-[10px] leading-snug text-amber-900/90">
                    That pack row does not match the finest segment of the primary biology headline;
                    markers still correspond to the keyed pack label, not a random row.
                  </span>
                ) : null}
                {supportDisplay.length > 0 ? (
                  <span className="text-gray-500">
                    {' '}
                    — ribosomal / translation / cell-cycle noise genes are hidden from this list;
                    see raw lists under Technical provenance.
                  </span>
                ) : null}
              </p>
              {supportHiddenByFilter ? (
                <p className="text-[11px] text-amber-900">
                  Stored support markers are present, but all were filtered as low-information for
                  display (e.g. RPL/RPS/MRPL/MRPS, MT-, selected housekeeping). Open{' '}
                  <span className="font-medium">Technical provenance</span> below for the raw list.
                </p>
              ) : (
                <MarkerEvidenceList
                  markers={supportDisplay}
                  geneOverlayGene={geneOverlayGene}
                  onGeneClick={onGeneClick}
                />
              )}
            </div>
          ) : cluster.evidence_hits.length > 0 ? (
            <div className="mt-1.5 text-[11px] text-gray-600">
              <p>
                Reference / retrieval matches (not gene-level proof in this export). Top match:{' '}
                <span className="font-medium text-gray-900">
                  {cluster.evidence_hits[0]?.label ?? '—'}
                </span>
                {cluster.evidence_hits[0]?.score != null ? (
                  <span className="font-mono text-gray-500">
                    {' '}
                    ({cluster.evidence_hits[0].score.toFixed(3)})
                  </span>
                ) : null}
                .
              </p>
            </div>
          ) : (
            <div className="mt-1.5 space-y-1">
              <p className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900">
                Fallback
              </p>
              <p className="text-[11px] text-gray-600">
                No annotation support-marker channel was stored for this cluster. Showing persisted
                DE-style markers for context only — not asserted as the basis for the pipeline /
                saved label.
              </p>
              {fallbackMarkersDisplay.length > 0 ? (
                <MarkerEvidenceList
                  markers={fallbackMarkersDisplay}
                  geneOverlayGene={geneOverlayGene}
                  onGeneClick={onGeneClick}
                />
              ) : (
                <p className="text-[11px] text-amber-900">
                  Persisted DE-style markers are only low-information for display after filtering.
                  See raw list under Technical provenance.
                </p>
              )}
            </div>
          )}
        </div>

        <div>
          <SectionTitle>Distinctive in this dataset</SectionTitle>
          <p className="mt-1 text-[11px] text-gray-500">
            Ranked from saved cluster marker list (DE-style where available). Ribosomal /
            translation-dominant and other noise genes are omitted from this view.
            {overlapsPipelineSupportMarkers
              ? ' Same genes also appear under pipeline support markers above.'
              : null}
          </p>
          {distinctive.length === 0 ? (
            <p className="mt-1 text-[11px] text-gray-400">
              {cluster.top_markers.length === 0
                ? 'No DE-style marker list in this artifact (cluster_markers not present). After updating the pipeline, re-export; pipeline support markers are listed above.'
                : topMarkersFiltered.length === 0
                  ? 'After filtering low-information genes, no DE-style markers remain for display. Raw list is under Technical provenance.'
                  : hasPipelineSupport
                    ? 'All informative DE markers overlap pipeline support markers — nothing additional to list here.'
                    : 'No additional markers to list.'}
            </p>
          ) : (
            <div className="mt-1.5">
              <MarkerEvidenceList
                markers={distinctive}
                geneOverlayGene={geneOverlayGene}
                onGeneClick={onGeneClick}
              />
            </div>
          )}
        </div>

        <div>
          <SectionTitle>Runner-ups & contradiction (vs pipeline / saved label)</SectionTitle>
          <div className="mt-1.5">
            {hasContradictionContent ? (
              <ContradictionEvidencePanel
                runnerUps={runnerUps}
                conservativeReason={cluster.conservative_reason ?? null}
                conservativeStatus={cluster.conservative_status ?? null}
                pipelineSavedLabel={cluster.label}
              />
            ) : (
              <p className="text-[11px] text-gray-400">No stored contradiction evidence.</p>
            )}
          </div>
        </div>

        <div>
          <SectionTitle>Technical display alias (rename)</SectionTitle>
          <div className="mt-1.5">
            <ClusterAliasEditor
              clusterId={cluster.cluster_id}
              pipelineSavedLabel={cluster.label}
              alias={displayAlias}
              onSave={onAliasSave}
              technicalIdKind={technicalIdKind}
            />
          </div>
        </div>

        <details className="rounded border border-dashed border-gray-200 bg-white/80 p-2 text-[10px] text-gray-600">
          <summary className="cursor-pointer font-medium text-gray-700">
            Technical provenance
          </summary>
          <ul className="mt-2 list-inside list-disc space-y-0.5">
            <li>Narrative summary: {cluster.summary ? 'shown above' : 'not stored in export'}</li>
            <li>Retrieval hit count (stored): {cluster.evidence_count}</li>
            <li>Annotation mode (uns): {cluster.annotation_mode ?? '—'}</li>
          </ul>
          <details className="mt-2 rounded border border-gray-100 bg-gray-50/80 p-2">
            <summary className="cursor-pointer font-medium text-gray-800">
              Raw stored marker lists (debug)
            </summary>
            <p className="mt-1.5 text-[10px] text-gray-500">
              Unfiltered strings from the artifact (same order as API). Used for diagnostics only.
            </p>
            <div className="mt-2 space-y-2 font-mono text-[10px] leading-snug text-gray-800">
              <div>
                <div className="font-sans text-[10px] font-semibold text-gray-600">
                  annotation_support_markers
                </div>
                <pre className="mt-0.5 max-h-32 overflow-auto whitespace-pre-wrap break-all">
                  {supportRaw.length ? supportRaw.join(', ') : '—'}
                </pre>
              </div>
              <div>
                <div className="font-sans text-[10px] font-semibold text-gray-600">top_markers</div>
                <pre className="mt-0.5 max-h-40 overflow-auto whitespace-pre-wrap break-all">
                  {topMarkersRaw.length ? topMarkersRaw.join(', ') : '—'}
                </pre>
              </div>
            </div>
          </details>
        </details>
      </div>
    </div>
  );
}
