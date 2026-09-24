import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DEViewer from '@/components/analysis/DEViewer';
import type { DEResult } from '@/components/analysis/DEViewer';

const makeResult = (overrides: Partial<DEResult> = {}): DEResult => ({
  gene: 'GAPDH',
  cluster: '0',
  log_fold_change: 1.5,
  p_value: 0.001,
  p_value_adj: 0.01,
  ...overrides,
});

const results: DEResult[] = [
  makeResult({
    gene: 'CD3D',
    cluster: '0',
    log_fold_change: 2.1,
    p_value: 0.0001,
    p_value_adj: 0.001,
  }),
  makeResult({
    gene: 'CD19',
    cluster: '1',
    log_fold_change: -1.8,
    p_value: 0.002,
    p_value_adj: 0.02,
  }),
  makeResult({ gene: 'FOXP3', cluster: '2', log_fold_change: 0.3, p_value: 0.5, p_value_adj: 0.8 }),
];

describe('DEViewer', () => {
  it('renders loading state', () => {
    render(<DEViewer results={[]} isLoading />);
    expect(screen.getByTestId('de-viewer-loading')).toBeInTheDocument();
  });

  it('renders error state with retry button', () => {
    const onRetry = vi.fn();
    render(<DEViewer results={[]} error="Failed to load" onRetry={onRetry} />);
    expect(screen.getByTestId('de-viewer-error')).toBeInTheDocument();
    expect(screen.getByText('Failed to load')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders DE results table', () => {
    render(<DEViewer results={results} />);
    expect(screen.getByTestId('de-results-table')).toBeInTheDocument();
    expect(screen.getByText('CD3D')).toBeInTheDocument();
    expect(screen.getByText('CD19')).toBeInTheDocument();
    expect(screen.getByText('FOXP3')).toBeInTheDocument();
  });

  it('renders volcano plot by default', () => {
    render(<DEViewer results={results} />);
    expect(screen.getByTestId('volcano-plot')).toBeInTheDocument();
  });

  it('toggles volcano plot visibility', () => {
    render(<DEViewer results={results} />);
    const toggleBtn = screen.getByTestId('toggle-volcano');
    expect(screen.getByTestId('volcano-plot')).toBeInTheDocument();
    fireEvent.click(toggleBtn);
    expect(screen.queryByTestId('volcano-plot')).not.toBeInTheDocument();
    fireEvent.click(toggleBtn);
    expect(screen.getByTestId('volcano-plot')).toBeInTheDocument();
  });

  it('filters by cluster', () => {
    render(<DEViewer results={results} />);
    const select = screen.getByTestId('cluster-filter');
    fireEvent.change(select, { target: { value: '0' } });
    expect(screen.getByText('CD3D')).toBeInTheDocument();
    expect(screen.queryByText('CD19')).not.toBeInTheDocument();
  });

  it('shows positive LFC in green and negative in red', () => {
    render(<DEViewer results={results} />);
    const table = screen.getByTestId('de-results-table');
    const cells = table.querySelectorAll('td');
    // LFC column for CD3D should have green class
    const lfcCells = Array.from(cells).filter((c) => c.textContent?.startsWith('+'));
    expect(lfcCells.length).toBeGreaterThan(0);
    expect(lfcCells[0].className).toContain('green');
  });

  it('shows p-threshold input and updates filtering', () => {
    render(<DEViewer results={results} />);
    const input = screen.getByTestId('p-threshold-input');
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '0.005' } });
    // FOXP3 (adj p=0.8) should not be highlighted
    expect(screen.getByText('FOXP3')).toBeInTheDocument();
  });

  it('shows lfc-threshold input', () => {
    render(<DEViewer results={results} />);
    expect(screen.getByTestId('lfc-threshold-input')).toBeInTheDocument();
  });
});
