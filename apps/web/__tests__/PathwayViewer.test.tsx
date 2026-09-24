import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PathwayViewer from '@/components/analysis/PathwayViewer';
import type { CrossDatasetPathwayResponse, InterpretPathwayResponse } from '@zerna/sdk';

const mockAnalysis: CrossDatasetPathwayResponse = {
  analysis_id: 'analysis-1',
  organization_id: 'org-1',
  dataset_ids: ['ds-1', 'ds-2'],
  pathway_database: 'MSigDB',
  aggregation_method: 'meta-analysis',
  status: 'completed',
  pathway_patterns: [
    {
      pathway_name: 'HALLMARK_GLYCOLYSIS',
      pathway_id: 'M5935',
      datasets_present: ['ds-1', 'ds-2'],
      aggregated_score: 0.82,
      p_value: 0.001,
      confidence: 0.9,
    },
    {
      pathway_name: 'HALLMARK_APOPTOSIS',
      pathway_id: 'M5901',
      datasets_present: ['ds-1'],
      aggregated_score: 0.45,
      p_value: 0.04,
      confidence: 0.6,
    },
  ],
  error_message: null,
  created_at: '2025-01-15T10:00:00Z',
  completed_at: '2025-01-15T10:05:00Z',
};

const mockInterpretation: InterpretPathwayResponse = {
  analysis_id: 'analysis-1',
  interpretation: 'The glycolysis pathway is consistently upregulated across datasets.',
  hypotheses: ['Tumor cells rely on aerobic glycolysis (Warburg effect)'],
  suggested_experiments: ['Measure lactate production in vitro'],
  model_used: 'gpt-4',
  cost_usd: 0.02,
  from_cache: false,
};

describe('PathwayViewer', () => {
  it('renders loading state', () => {
    render(<PathwayViewer isLoading />);
    expect(screen.getByTestId('pathway-viewer-loading')).toBeInTheDocument();
  });

  it('renders error state with retry', () => {
    const onRetry = vi.fn();
    render(<PathwayViewer error="Network error" onRetry={onRetry} />);
    expect(screen.getByTestId('pathway-viewer-error')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders enrichment tab by default', () => {
    render(<PathwayViewer />);
    expect(screen.getByTestId('pathway-viewer')).toBeInTheDocument();
    expect(screen.getByTestId('tab-enrichment')).toBeInTheDocument();
  });

  it('shows cross-dataset tab when analysis provided', () => {
    render(<PathwayViewer crossDatasetAnalysis={mockAnalysis} />);
    expect(screen.getByTestId('tab-cross-dataset')).toBeInTheDocument();
  });

  it('renders pathway patterns in cross-dataset tab', () => {
    render(<PathwayViewer crossDatasetAnalysis={mockAnalysis} />);
    fireEvent.click(screen.getByTestId('tab-cross-dataset'));
    expect(screen.getByTestId('cross-dataset-panel')).toBeInTheDocument();
    expect(screen.getByTestId('pathway-enrichment-table')).toBeInTheDocument();
    expect(screen.getByText('HALLMARK_GLYCOLYSIS')).toBeInTheDocument();
    expect(screen.getByText('HALLMARK_APOPTOSIS')).toBeInTheDocument();
  });

  it('shows interpret button in cross-dataset tab', () => {
    const onInterpret = vi.fn();
    render(
      <PathwayViewer crossDatasetAnalysis={mockAnalysis} onRequestInterpretation={onInterpret} />
    );
    fireEvent.click(screen.getByTestId('tab-cross-dataset'));
    const btn = screen.getByTestId('interpret-btn');
    fireEvent.click(btn);
    expect(onInterpret).toHaveBeenCalledOnce();
  });

  it('shows interpretation tab when interpretation provided', () => {
    render(
      <PathwayViewer crossDatasetAnalysis={mockAnalysis} interpretation={mockInterpretation} />
    );
    expect(screen.getByTestId('tab-interpretation')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('tab-interpretation'));
    expect(screen.getByTestId('interpretation-panel')).toBeInTheDocument();
    expect(screen.getByText(/glycolysis pathway/i)).toBeInTheDocument();
  });

  it('renders hypotheses list', () => {
    render(
      <PathwayViewer crossDatasetAnalysis={mockAnalysis} interpretation={mockInterpretation} />
    );
    fireEvent.click(screen.getByTestId('tab-interpretation'));
    expect(screen.getByTestId('hypotheses-list')).toBeInTheDocument();
    expect(screen.getByText(/Warburg effect/i)).toBeInTheDocument();
  });

  it('renders suggested experiments', () => {
    render(
      <PathwayViewer crossDatasetAnalysis={mockAnalysis} interpretation={mockInterpretation} />
    );
    fireEvent.click(screen.getByTestId('tab-interpretation'));
    expect(screen.getByTestId('experiments-list')).toBeInTheDocument();
    expect(screen.getByText(/lactate production/i)).toBeInTheDocument();
  });

  it('shows pathway select when cell scores provided', () => {
    const cellScores = [
      { cell_id: 'c1', pathway: 'HALLMARK_GLYCOLYSIS', score: 0.8 },
      { cell_id: 'c2', pathway: 'HALLMARK_APOPTOSIS', score: 0.3 },
    ];
    render(<PathwayViewer cellScores={cellScores} />);
    expect(screen.getByTestId('pathway-select')).toBeInTheDocument();
  });
});
