import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import UploadForm from '@/components/datasets/UploadForm';

vi.mock('@/lib/dataset-actions', () => ({
  uploadDatasetAction: vi.fn(),
}));

vi.mock('react-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-dom')>();
  return {
    ...actual,
    useFormState: (action: unknown, initial: unknown) => [initial, action],
  };
});

vi.mock('@/components/datasets/FileDropZone', () => ({
  default: ({ onChange, error }: { onChange?: (files: File[]) => void; error?: string }) => (
    <div data-testid="file-drop-zone">
      <button
        type="button"
        data-testid="stage-ambiguous-mtx"
        onClick={() =>
          onChange?.([
            new File([], 'matrix1.mtx'),
            new File([], 'matrix2.mtx'),
            new File([], 'barcodes.tsv'),
            new File([], 'genes.tsv'),
          ])
        }
      >
        Stage ambiguous MTX
      </button>
      <button
        type="button"
        data-testid="stage-multi-h5"
        onClick={() => onChange?.([new File([], 'a.h5'), new File([], 'b.h5')])}
      >
        Stage multi h5
      </button>
      <button
        type="button"
        data-testid="stage-two-10x-bundles"
        onClick={() =>
          onChange?.([
            new File([], 'donor1_matrix.mtx'),
            new File([], 'donor1_barcodes.tsv'),
            new File([], 'donor1_features.tsv'),
            new File([], 'donor2_matrix.mtx'),
            new File([], 'donor2_barcodes.tsv'),
            new File([], 'donor2_genes.tsv'),
          ])
        }
      >
        Stage two 10x bundles
      </button>
      <button
        type="button"
        data-testid="stage-two-csv"
        onClick={() => onChange?.([new File([], 'a.csv'), new File([], 'b.csv')])}
      >
        Stage two csv
      </button>
      <button
        type="button"
        data-testid="stage-mixed-bundle-and-file"
        onClick={() =>
          onChange?.([
            new File([], 'donor1_matrix.mtx'),
            new File([], 'donor1_barcodes.tsv'),
            new File([], 'donor1_genes.tsv'),
            new File([], 'extra_counts.csv'),
          ])
        }
      >
        Stage mixed bundle and file
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  ),
}));

describe('UploadForm', () => {
  it('renders combined dataset fields and per-file metadata section label', () => {
    render(<UploadForm />);

    expect(screen.getByLabelText(/combined dataset name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/extra metadata/i)).toBeInTheDocument();
    expect(screen.getByTestId('file-drop-zone')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /per-file metadata/i })).not.toBeInTheDocument();
  });

  it('renders submit and cancel', () => {
    render(<UploadForm />);
    expect(screen.getByRole('button', { name: /upload dataset/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /cancel/i })).toHaveAttribute('href', '/datasets');
  });

  it('disables upload until at least one file is staged', () => {
    render(<UploadForm />);
    expect(screen.getByRole('button', { name: /upload dataset/i })).toBeDisabled();
  });

  it('shows blocking preflight for unprefixed multi-MTX and disables submit', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-ambiguous-mtx'));
    expect(screen.getByTestId('upload-preflight-blocking')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload dataset/i })).toBeDisabled();
  });

  it('shows non-blocking warning for multi-file 10x h5', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-multi-h5'));
    expect(screen.getByTestId('upload-preflight-warnings')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload dataset/i })).not.toBeDisabled();
  });

  it('groups two prefixed 10x bundles into two sample cards', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-10x-bundles'));
    expect(screen.getByText(/per-sample metadata/i)).toBeInTheDocument();
    const bundleCards = document.querySelectorAll('[data-unit-kind="bundle"]');
    expect(bundleCards.length).toBe(2);
    expect(screen.queryByTestId('upload-preflight-blocking')).toBeNull();
    expect(screen.getByRole('button', { name: /upload dataset/i })).not.toBeDisabled();
  });

  it('shows logical dataset summary with correct counts for two 10x bundles', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-10x-bundles'));
    const panel = screen.getByTestId('logical-dataset-summary');
    expect(panel).toHaveTextContent(/2 logical datasets ready/i);
    expect(panel).toHaveTextContent(/2 detected as 10x bundles/i);
    expect(panel).toHaveTextContent(/6 raw files uploaded/i);
  });

  it('labels 10x bundle cards and lists matrix, barcodes, and features or genes', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-10x-bundles'));
    expect(screen.getAllByText('10x bundle')).toHaveLength(2);
    expect(screen.getAllByText(/Prefix:/i).length).toBeGreaterThanOrEqual(2);
    const dls = screen.getAllByTestId(/^bundle-included-files-/);
    expect(dls.length).toBe(2);
    expect(dls[0]).toHaveTextContent(/Matrix/i);
    expect(dls[0]).toHaveTextContent(/Barcodes/i);
    expect(dls[0]).toHaveTextContent(/Features/i);
    expect(dls[1]).toHaveTextContent(/Genes/i);
  });

  it('labels file-based units and summary for two csv files', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-csv'));
    expect(screen.getAllByText('File upload')).toHaveLength(2);
    const panel = screen.getByTestId('logical-dataset-summary');
    expect(panel).toHaveTextContent(/2 logical datasets ready/i);
    expect(panel).toHaveTextContent(/2 detected as file-based uploads/i);
    expect(panel).toHaveTextContent(/2 raw files uploaded/i);
  });

  it('shows submit-area confirmation with logical dataset count', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-csv'));
    const hint = screen.getByTestId('submit-logical-dataset-hint');
    expect(hint).toHaveTextContent(/2 logical datasets/i);
    expect(hint).toHaveTextContent(/merged into one Zerna dataset/i);
  });

  it('mixed bundle and file shows both counts in summary and submit hint', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-mixed-bundle-and-file'));
    const panel = screen.getByTestId('logical-dataset-summary');
    expect(panel).toHaveTextContent(/2 logical datasets ready/i);
    expect(panel).toHaveTextContent(/1 detected as 10x bundle/i);
    expect(panel).toHaveTextContent(/1 detected as file-based upload/i);
    expect(panel).toHaveTextContent(/4 raw files uploaded/i);
    expect(screen.getByTestId('submit-logical-dataset-hint')).toHaveTextContent(
      /2 logical datasets.*10x bundle.*file-based/i
    );
  });

  it('shows metadata-per-logical-dataset explanation when staged', () => {
    render(<UploadForm />);
    fireEvent.click(screen.getByTestId('stage-two-csv'));
    expect(screen.getByText(/Metadata is assigned per logical dataset/i)).toBeInTheDocument();
  });
});
