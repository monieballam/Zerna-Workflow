import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ClusterInspector from './ClusterInspector';
import type { ClusterInspectorSummary } from './cluster-inspector-types';

function summary(
  id: string,
  label: string,
  over?: Partial<ClusterInspectorSummary>
): ClusterInspectorSummary {
  return {
    cluster_id: id,
    n_cells: 5,
    label,
    confidence: 'high',
    summary: '',
    top_markers: [],
    evidence_count: 0,
    evidence_hits: [],
    top_cell_types: [],
    ...over,
  };
}

describe('ClusterInspector', () => {
  it('separates primary biology headline from pipeline / saved label and technical display alias', () => {
    const c = summary('0', 'Annot from server');
    render(
      <ClusterInspector
        clusterSummaries={[c]}
        selectedClusterId="0"
        onSelectCluster={() => {}}
        selectedCluster={c}
        geneOverlayGene={null}
        onMarkerClick={() => {}}
        listLabelFor={() => 'Immune | T cells | CD8'}
        aliasForSelected="Curated note"
        onAliasSave={() => {}}
        userClusterAliases={{ '0': 'Curated note' }}
      />
    );

    const detail = screen.getByTestId('cluster-detail');
    expect(screen.getByTestId('cluster-detail-biology-headline-caption')).toHaveTextContent(
      'Primary biology headline'
    );
    expect(within(detail).getByRole('heading', { level: 3 })).toHaveTextContent(
      'Immune | T cells | CD8'
    );
    expect(within(detail).getByTestId('cluster-detail-pipeline-saved')).toHaveTextContent(
      'Annot from server'
    );
    expect(within(detail).getByTestId('cluster-detail-technical-alias')).toHaveTextContent(
      'Curated note'
    );
  });

  it('does not show legacy “Assigned label” in the inspector detail block', () => {
    const c = summary('1', 'X');
    render(
      <ClusterInspector
        clusterSummaries={[c]}
        selectedClusterId="1"
        onSelectCluster={() => {}}
        selectedCluster={c}
        geneOverlayGene={null}
        onMarkerClick={() => {}}
        listLabelFor={() => 'Immune | B cells'}
        aliasForSelected=""
        onAliasSave={() => {}}
      />
    );
    expect(screen.queryByText(/^Assigned label$/)).toBeNull();
  });
});
