import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AnnotationEvidenceCard from './AnnotationEvidenceCard';
import type { ClusterInspectorSummary } from './cluster-inspector-types';

function baseCluster(over: Partial<ClusterInspectorSummary>): ClusterInspectorSummary {
  return {
    cluster_id: '0',
    n_cells: 12,
    label: 'T cell',
    confidence: 'high',
    summary: '',
    top_markers: [],
    evidence_count: 0,
    evidence_hits: [],
    top_cell_types: [],
    ...over,
  };
}

describe('AnnotationEvidenceCard', () => {
  it('shows amber notice when support markers are only low-information after filtering', () => {
    render(
      <AnnotationEvidenceCard
        cluster={baseCluster({
          annotation_support_markers: ['RPL13', 'RPS4X', 'MALAT1'],
          top_markers: [],
        })}
        displayAlias=""
        onAliasSave={() => {}}
        geneOverlayGene={null}
        onGeneClick={() => {}}
      />
    );
    expect(screen.getByText(/all were filtered as low-information for display/i)).toBeTruthy();
  });

  it('Identity uses pipeline / saved label and technical display alias (no Assigned label)', () => {
    render(
      <AnnotationEvidenceCard
        cluster={baseCluster({ label: 'Server pipeline label' })}
        displayAlias="Browser-only alias"
        onAliasSave={() => {}}
        geneOverlayGene={null}
        onGeneClick={() => {}}
      />
    );
    expect(screen.queryByText(/^Assigned label$/)).toBeNull();
    expect(screen.getByText('Pipeline / saved label')).toBeTruthy();
    expect(screen.getByTestId('evidence-pipeline-saved-label')).toHaveTextContent(
      'Server pipeline label'
    );
    expect(screen.getByText('Technical display alias')).toBeTruthy();
    expect(screen.getByTestId('evidence-technical-alias')).toHaveTextContent('Browser-only alias');
  });

  it('contradiction runner-ups reference pipeline / saved label wording', () => {
    render(
      <AnnotationEvidenceCard
        cluster={baseCluster({
          label: 'Chosen type',
          runner_up_labels: [{ cell_type: 'Other type', score: 0.31, n_markers: 1 }],
        })}
        displayAlias=""
        onAliasSave={() => {}}
        geneOverlayGene={null}
        onGeneClick={() => {}}
      />
    );
    expect(screen.getByText(/scored lower than the\s+pipeline \/ saved label/i)).toBeTruthy();
    const runnerUpRow = screen.getByText('Other type').closest('li');
    expect(runnerUpRow?.textContent).toContain('pipeline / saved label');
    expect(runnerUpRow?.textContent).toContain('Chosen type');
  });

  it('renders informative distinctive genes and omits ribosomal from main lists', () => {
    render(
      <AnnotationEvidenceCard
        cluster={baseCluster({
          annotation_support_markers: ['CD3D'],
          top_markers: ['RPL3', 'CD8A', 'RPS4X', 'MS4A1'],
        })}
        displayAlias=""
        onAliasSave={() => {}}
        geneOverlayGene={null}
        onGeneClick={() => {}}
      />
    );
    expect(screen.getAllByRole('button', { name: 'CD3D' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'CD8A' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'RPL3' })).toBeNull();
  });
});
