import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ExportCenter from '@/components/analysis/ExportCenter';
import type { ExportStatusResponse } from '@zerna/sdk';

const mockStatus: ExportStatusResponse = {
  run_id: 'run-1',
  available_exports: ['h5ad', 'de_results'],
};

const mockOnRequestExport = vi.fn().mockResolvedValue({});
const mockOnGetDownloadUrl = vi
  .fn()
  .mockResolvedValue({ url: 'https://s3.example.com/export.h5ad' });

describe('ExportCenter', () => {
  beforeEach(() => {
    vi.stubGlobal('open', vi.fn());
  });

  it('renders loading state', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={null}
        isLoading
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('export-center-loading')).toBeInTheDocument();
  });

  it('renders error state with retry', () => {
    const onRetry = vi.fn();
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={null}
        error="Failed to load"
        onRetry={onRetry}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('export-center-error')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders all export format cards', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('export-card-h5ad')).toBeInTheDocument();
    expect(screen.getByTestId('export-card-de_results')).toBeInTheDocument();
    expect(screen.getByTestId('export-card-embeddings')).toBeInTheDocument();
    expect(screen.getByTestId('export-card-report')).toBeInTheDocument();
  });

  it('shows available badge for ready exports', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('available-badge-h5ad')).toBeInTheDocument();
    expect(screen.getByTestId('available-badge-de_results')).toBeInTheDocument();
    expect(screen.queryByTestId('available-badge-embeddings')).not.toBeInTheDocument();
  });

  it('shows download button for available exports', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('download-btn-h5ad')).toBeInTheDocument();
    expect(screen.getByTestId('download-btn-de_results')).toBeInTheDocument();
  });

  it('shows generate button for unavailable exports', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('generate-btn-embeddings')).toBeInTheDocument();
    expect(screen.getByTestId('generate-btn-report')).toBeInTheDocument();
  });

  it('calls onGetDownloadUrl when download button clicked', async () => {
    const getUrl = vi.fn().mockResolvedValue({ url: 'https://s3.example.com/file.h5ad' });
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={getUrl}
      />
    );
    fireEvent.click(screen.getByTestId('download-btn-h5ad'));
    await waitFor(() => expect(getUrl).toHaveBeenCalledWith('run-1', 'h5ad'));
    expect(window.open).toHaveBeenCalledWith(
      'https://s3.example.com/file.h5ad',
      '_blank',
      'noopener,noreferrer'
    );
  });

  it('calls onRequestExport when generate button clicked', async () => {
    const requestExport = vi.fn().mockResolvedValue({});
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={requestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    fireEvent.click(screen.getByTestId('generate-btn-embeddings'));
    await waitFor(() => expect(requestExport).toHaveBeenCalledWith('run-1', 'embeddings'));
  });

  it('renders reproducibility report preview', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={mockStatus}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
        softwareVersions={{ scanpy: '1.9.3' }}
        randomSeed={42}
        parameters={{ resolution: 0.5 }}
      />
    );
    expect(screen.getByTestId('report-preview')).toBeInTheDocument();
    expect(screen.getByText('run-1')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('scanpy: 1.9.3')).toBeInTheDocument();
  });

  it('handles null export status gracefully', () => {
    render(
      <ExportCenter
        runId="run-1"
        exportStatus={null}
        onRequestExport={mockOnRequestExport}
        onGetDownloadUrl={mockOnGetDownloadUrl}
      />
    );
    expect(screen.getByTestId('export-center')).toBeInTheDocument();
    // All exports should show generate buttons when status is null
    expect(screen.getByTestId('generate-btn-h5ad')).toBeInTheDocument();
  });
});
