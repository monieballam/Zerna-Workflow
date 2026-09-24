import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FileDropZone from '@/components/datasets/FileDropZone';

describe('FileDropZone', () => {
  it('renders drop zone with instructions', () => {
    render(<FileDropZone />);

    expect(screen.getByText(/click to browse/i)).toBeInTheDocument();
    expect(screen.getByText(/drag and drop/i)).toBeInTheDocument();
    expect(screen.getByText(/\.h5ad, \.h5, \.mtx, \.csv, \.tsv/i)).toBeInTheDocument();
  });

  it('shows validation error when provided', () => {
    render(<FileDropZone error="Unsupported format: data.bam" />);

    expect(screen.getByText('Unsupported format: data.bam')).toBeInTheDocument();
  });

  it('applies error styling when error prop is set', () => {
    render(<FileDropZone error="Some error" />);

    const dropZone = screen.getByRole('button', { name: /drop files/i });
    expect(dropZone.className).toContain('border-red');
  });

  it('adds files via file input and shows them in the list', () => {
    render(<FileDropZone />);

    const input = screen.getByLabelText('File input');
    const file = new File(['content'], 'sample.h5ad', { type: 'application/octet-stream' });

    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('sample.h5ad')).toBeInTheDocument();
  });

  it('rejects files with unsupported extensions', () => {
    render(<FileDropZone />);

    const input = screen.getByLabelText('File input');
    const badFile = new File(['content'], 'data.bam', { type: 'application/octet-stream' });

    fireEvent.change(input, { target: { files: [badFile] } });

    expect(screen.queryByText('data.bam')).not.toBeInTheDocument();
  });

  it('removes a file when the remove button is clicked', () => {
    render(<FileDropZone />);

    const input = screen.getByLabelText('File input');
    const file = new File(['content'], 'cells.csv', { type: 'text/csv' });

    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText('cells.csv')).toBeInTheDocument();

    const removeBtn = screen.getByRole('button', { name: /remove cells\.csv/i });
    fireEvent.click(removeBtn);

    expect(screen.queryByText('cells.csv')).not.toBeInTheDocument();
  });

  it('does not add duplicate files', () => {
    render(<FileDropZone />);

    const input = screen.getByLabelText('File input');
    const file = new File(['content'], 'data.h5ad', { type: 'application/octet-stream' });

    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(input, { target: { files: [file] } });

    const items = screen.getAllByText('data.h5ad');
    expect(items).toHaveLength(1);
  });

  it('applies dragging styles on dragover', () => {
    render(<FileDropZone />);

    const dropZone = screen.getByRole('button', { name: /drop files/i });
    fireEvent.dragOver(dropZone);

    expect(dropZone.className).toContain('border-blue-500');
  });
});
