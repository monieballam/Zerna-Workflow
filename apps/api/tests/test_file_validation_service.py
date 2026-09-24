"""Unit tests for FileValidationService."""

import gzip
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.io import mmwrite
from scipy.sparse import csr_matrix

from apps.api.services.file_validation_service import (
    FileValidationService,
)


@pytest.fixture
def validation_service():
    """Create a FileValidationService instance."""
    return FileValidationService()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestH5adValidation:
    """Tests for h5ad file validation."""

    @pytest.mark.asyncio
    async def test_valid_h5ad_file(self, validation_service, temp_dir):
        """Test validation of a valid h5ad file."""
        import anndata as ad

        # Enable writing nullable strings for anndata >= 0.11
        ad.settings.allow_write_nullable_strings = True

        # Create a simple AnnData object
        n_obs = 100
        n_vars = 50
        X = np.random.rand(n_obs, n_vars)
        obs = pd.DataFrame({"cell_type": ["A"] * n_obs}, index=[f"cell_{i}" for i in range(n_obs)])
        var = pd.DataFrame(
            {"gene_name": [f"gene_{i}" for i in range(n_vars)]},
            index=[f"gene_{i}" for i in range(n_vars)],
        )

        adata = ad.AnnData(X=X, obs=obs, var=var)

        # Save to file
        h5ad_file = temp_dir / "test.h5ad"
        adata.write_h5ad(h5ad_file)

        # Validate
        result = await validation_service.validate_h5ad(h5ad_file)

        assert result.is_valid is True
        assert result.error_message is None
        assert result.metadata is not None
        assert result.metadata.cell_count == n_obs
        assert result.metadata.gene_count == n_vars
        assert result.metadata.format == "h5ad"
        assert "obs_columns" in result.metadata.additional_metadata
        assert "cell_type" in result.metadata.additional_metadata["obs_columns"]

    @pytest.mark.asyncio
    async def test_invalid_h5ad_missing_x(self, validation_service, temp_dir):
        """Test validation of h5ad file missing X matrix."""
        import h5py

        # Create an HDF5 file without X
        h5ad_file = temp_dir / "invalid.h5ad"
        with h5py.File(h5ad_file, "w") as f:
            f.create_dataset("obs", data=[1, 2, 3])

        result = await validation_service.validate_h5ad(h5ad_file)

        assert result.is_valid is False
        assert "missing 'X'" in result.error_message

    @pytest.mark.asyncio
    async def test_h5ad_with_layers(self, validation_service, temp_dir):
        """Test validation of h5ad file with layers."""
        import anndata as ad

        # Enable writing nullable strings for anndata >= 0.11
        ad.settings.allow_write_nullable_strings = True

        n_obs = 50
        n_vars = 30
        X = np.random.rand(n_obs, n_vars)
        adata = ad.AnnData(X=X)
        adata.layers["raw"] = X.copy()
        adata.layers["normalized"] = X * 2

        h5ad_file = temp_dir / "with_layers.h5ad"
        adata.write_h5ad(h5ad_file)

        result = await validation_service.validate_h5ad(h5ad_file)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_obs
        assert result.metadata.gene_count == n_vars
        assert "layers" in result.metadata.additional_metadata
        assert "raw" in result.metadata.additional_metadata["layers"]
        assert "normalized" in result.metadata.additional_metadata["layers"]

    @pytest.mark.asyncio
    async def test_valid_h5ad_uses_backed_mode(self, validation_service, temp_dir, monkeypatch):
        """Large H5AD validation should avoid loading X eagerly."""
        import anndata as ad

        adata = ad.AnnData(X=np.eye(3, dtype=np.float32))
        h5ad_file = temp_dir / "backed.h5ad"
        adata.write_h5ad(h5ad_file)

        calls: list[tuple[Path, str | None]] = []

        class _Closable:
            closed = False

            def close(self):
                self.closed = True

        closable = _Closable()

        class _DummyBacked:
            n_obs = 3
            n_vars = 3
            obs = pd.DataFrame(index=["a", "b", "c"])
            var = pd.DataFrame(index=["g1", "g2", "g3"])
            layers = {}
            obsm = {}
            varm = {}
            file = closable

        def _fake_read_h5ad(path, backed=None):
            calls.append((Path(path), backed))
            return _DummyBacked()

        monkeypatch.setattr(ad, "read_h5ad", _fake_read_h5ad)

        result = await validation_service.validate_h5ad(h5ad_file)

        assert result.is_valid is True
        assert calls == [(h5ad_file, "r")]
        assert closable.closed is True


class Test10xH5Validation:
    """Tests for 10x HDF5 file validation."""

    @pytest.mark.asyncio
    async def test_valid_10x_h5_file(self, validation_service, temp_dir):
        """Test validation of a valid 10x h5 file."""
        import h5py

        n_genes = 100
        n_cells = 50

        h5_file = temp_dir / "test_10x.h5"
        with h5py.File(h5_file, "w") as f:
            matrix_group = f.create_group("matrix")

            # Create sparse matrix data
            data = np.random.rand(1000)
            indices = np.random.randint(0, n_genes, 1000)
            indptr = np.sort(np.random.randint(0, 1000, n_cells + 1))
            indptr[0] = 0
            indptr[-1] = 1000

            matrix_group.create_dataset("data", data=data)
            matrix_group.create_dataset("indices", data=indices)
            matrix_group.create_dataset("indptr", data=indptr)
            matrix_group.create_dataset("shape", data=[n_genes, n_cells])
            matrix_group.create_dataset(
                "barcodes", data=[f"CELL_{i}".encode() for i in range(n_cells)]
            )

            # Create features group
            features_group = matrix_group.create_group("features")
            features_group.create_dataset(
                "name", data=[f"GENE_{i}".encode() for i in range(n_genes)]
            )

        result = await validation_service.validate_10x_h5(h5_file)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes
        assert result.metadata.format == "10x_h5"

    @pytest.mark.asyncio
    async def test_invalid_10x_h5_missing_matrix(self, validation_service, temp_dir):
        """Test validation of 10x h5 file missing matrix group."""
        import h5py

        h5_file = temp_dir / "invalid_10x.h5"
        with h5py.File(h5_file, "w") as f:
            f.create_dataset("data", data=[1, 2, 3])

        result = await validation_service.validate_10x_h5(h5_file)

        assert result.is_valid is False
        assert "missing 'matrix' group" in result.error_message

    @pytest.mark.asyncio
    async def test_invalid_10x_h5_missing_required_keys(self, validation_service, temp_dir):
        """Test validation of 10x h5 file missing required keys."""
        import h5py

        h5_file = temp_dir / "incomplete_10x.h5"
        with h5py.File(h5_file, "w") as f:
            matrix_group = f.create_group("matrix")
            matrix_group.create_dataset("data", data=[1, 2, 3])
            # Missing: barcodes, indices, indptr, shape

        result = await validation_service.validate_10x_h5(h5_file)

        assert result.is_valid is False
        assert "missing required keys" in result.error_message


class Test10xMtxValidation:
    """Tests for 10x MTX format validation."""

    @pytest.mark.asyncio
    async def test_valid_10x_mtx_directory(self, validation_service, temp_dir):
        """Test validation of a valid 10x MTX directory."""
        n_genes = 100
        n_cells = 50

        # Create matrix
        matrix = csr_matrix(np.random.rand(n_genes, n_cells))
        matrix_file = temp_dir / "matrix.mtx"
        mmwrite(matrix_file, matrix)

        # Create genes file
        genes_file = temp_dir / "genes.tsv"
        with open(genes_file, "w") as f:
            for i in range(n_genes):
                f.write(f"GENE_{i}\tGene_{i}\n")

        # Create barcodes file
        barcodes_file = temp_dir / "barcodes.tsv"
        with open(barcodes_file, "w") as f:
            for i in range(n_cells):
                f.write(f"CELL_{i}\n")

        result = await validation_service.validate_10x_mtx(temp_dir)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes
        assert result.metadata.format == "10x_mtx"
        assert "nnz" in result.metadata.additional_metadata

    @pytest.mark.asyncio
    async def test_valid_10x_mtx_with_features(self, validation_service, temp_dir):
        """Test validation of 10x MTX with features.tsv instead of genes.tsv."""
        n_genes = 80
        n_cells = 40

        matrix = csr_matrix(np.random.rand(n_genes, n_cells))
        matrix_file = temp_dir / "matrix.mtx"
        mmwrite(matrix_file, matrix)

        # Use features.tsv instead of genes.tsv
        features_file = temp_dir / "features.tsv"
        with open(features_file, "w") as f:
            for i in range(n_genes):
                f.write(f"GENE_{i}\tGene_{i}\tGene Expression\n")

        barcodes_file = temp_dir / "barcodes.tsv"
        with open(barcodes_file, "w") as f:
            for i in range(n_cells):
                f.write(f"CELL_{i}\n")

        result = await validation_service.validate_10x_mtx(temp_dir)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes

    @pytest.mark.asyncio
    async def test_valid_10x_mtx_gzipped(self, validation_service, temp_dir):
        """Test validation of 10x MTX with gzipped files."""
        n_genes = 60
        n_cells = 30

        # Create gzipped matrix
        matrix = csr_matrix(np.random.rand(n_genes, n_cells))
        matrix_file = temp_dir / "matrix.mtx.gz"
        with gzip.open(matrix_file, "wb") as f:
            mmwrite(f, matrix)

        # Create gzipped genes file
        genes_file = temp_dir / "genes.tsv.gz"
        with gzip.open(genes_file, "wt") as f:
            for i in range(n_genes):
                f.write(f"GENE_{i}\tGene_{i}\n")

        # Create gzipped barcodes file
        barcodes_file = temp_dir / "barcodes.tsv.gz"
        with gzip.open(barcodes_file, "wt") as f:
            for i in range(n_cells):
                f.write(f"CELL_{i}\n")

        result = await validation_service.validate_10x_mtx(temp_dir)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes

    @pytest.mark.asyncio
    async def test_valid_10x_mtx_zip_archive(self, validation_service, temp_dir):
        """Test validation of 10x MTX in a zip archive."""
        n_genes = 50
        n_cells = 25

        # Create temporary directory for files
        mtx_dir = temp_dir / "mtx_data"
        mtx_dir.mkdir()

        matrix = csr_matrix(np.random.rand(n_genes, n_cells))
        matrix_file = mtx_dir / "matrix.mtx"
        mmwrite(matrix_file, matrix)

        genes_file = mtx_dir / "genes.tsv"
        with open(genes_file, "w") as f:
            for i in range(n_genes):
                f.write(f"GENE_{i}\tGene_{i}\n")

        barcodes_file = mtx_dir / "barcodes.tsv"
        with open(barcodes_file, "w") as f:
            for i in range(n_cells):
                f.write(f"CELL_{i}\n")

        # Create zip archive
        zip_file = temp_dir / "mtx_data.zip"
        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.write(matrix_file, "matrix.mtx")
            zf.write(genes_file, "genes.tsv")
            zf.write(barcodes_file, "barcodes.tsv")

        result = await validation_service.validate_10x_mtx(zip_file)

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes

    @pytest.mark.asyncio
    async def test_invalid_10x_mtx_missing_files(self, validation_service, temp_dir):
        """Test validation of 10x MTX with missing files."""
        # Only create matrix file
        matrix = csr_matrix(np.random.rand(50, 25))
        matrix_file = temp_dir / "matrix.mtx"
        mmwrite(matrix_file, matrix)

        result = await validation_service.validate_10x_mtx(temp_dir)

        assert result.is_valid is False
        assert "missing required files" in result.error_message

    @pytest.mark.asyncio
    async def test_invalid_10x_mtx_count_mismatch(self, validation_service, temp_dir):
        """Test validation of 10x MTX with mismatched counts."""
        n_genes = 100
        n_cells = 50

        matrix = csr_matrix(np.random.rand(n_genes, n_cells))
        matrix_file = temp_dir / "matrix.mtx"
        mmwrite(matrix_file, matrix)

        # Create genes file with wrong count
        genes_file = temp_dir / "genes.tsv"
        with open(genes_file, "w") as f:
            for i in range(n_genes - 10):  # Wrong count
                f.write(f"GENE_{i}\tGene_{i}\n")

        barcodes_file = temp_dir / "barcodes.tsv"
        with open(barcodes_file, "w") as f:
            for i in range(n_cells):
                f.write(f"CELL_{i}\n")

        result = await validation_service.validate_10x_mtx(temp_dir)

        assert result.is_valid is False
        assert "Gene count mismatch" in result.error_message


class TestCsvTsvValidation:
    """Tests for CSV/TSV file validation."""

    @pytest.mark.asyncio
    async def test_valid_csv_file(self, validation_service, temp_dir):
        """Test validation of a valid CSV file."""
        n_genes = 100
        n_cells = 50

        # Create CSV file (genes x cells)
        data = np.random.rand(n_genes, n_cells)
        df = pd.DataFrame(
            data,
            index=[f"GENE_{i}" for i in range(n_genes)],
            columns=[f"CELL_{i}" for i in range(n_cells)],
        )

        csv_file = temp_dir / "expression.csv"
        df.to_csv(csv_file)

        result = await validation_service.validate_csv_tsv(csv_file, "csv")

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells

    @pytest.mark.asyncio
    async def test_valid_gzipped_csv_file(self, validation_service, temp_dir):
        """Test validation of a gzip-compressed CSV count matrix."""
        n_genes = 12
        n_cells = 7

        data = np.random.rand(n_genes, n_cells)
        df = pd.DataFrame(
            data,
            index=[f"GENE_{i}" for i in range(n_genes)],
            columns=[f"CELL_{i}" for i in range(n_cells)],
        )

        csv_file = temp_dir / "BMET1-Tumor.count.csv.gz"
        with gzip.open(csv_file, "wt") as handle:
            df.to_csv(handle)

        result = await validation_service.validate_csv_tsv(csv_file, "csv")

        assert result.is_valid is True
        assert result.metadata is not None
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes
        assert result.metadata.gene_count == n_genes
        assert result.metadata.format == "csv"
        assert result.metadata.additional_metadata["separator"] == ","

    @pytest.mark.asyncio
    async def test_valid_tsv_file(self, validation_service, temp_dir):
        """Test validation of a valid TSV file."""
        n_genes = 80
        n_cells = 40

        data = np.random.rand(n_genes, n_cells)
        df = pd.DataFrame(
            data,
            index=[f"GENE_{i}" for i in range(n_genes)],
            columns=[f"CELL_{i}" for i in range(n_cells)],
        )

        tsv_file = temp_dir / "expression.tsv"
        df.to_csv(tsv_file, sep="\t")

        result = await validation_service.validate_csv_tsv(tsv_file, "tsv")

        assert result.is_valid is True
        assert result.metadata.cell_count == n_cells
        assert result.metadata.gene_count == n_genes
        assert result.metadata.format == "tsv"
        assert result.metadata.additional_metadata["separator"] == "\t"

    @pytest.mark.asyncio
    async def test_invalid_csv_empty_file(self, validation_service, temp_dir):
        """Test validation of an empty CSV file."""
        csv_file = temp_dir / "empty.csv"
        csv_file.write_text("")

        result = await validation_service.validate_csv_tsv(csv_file, "csv")

        assert result.is_valid is False
        # Check for either "empty" or "no columns" in error message
        assert (
            "empty" in result.error_message.lower() or "no columns" in result.error_message.lower()
        )

    @pytest.mark.asyncio
    async def test_csv_with_single_cell(self, validation_service, temp_dir):
        """Test validation of CSV with single cell."""
        n_genes = 50

        data = np.random.rand(n_genes, 1)
        df = pd.DataFrame(
            data,
            index=[f"GENE_{i}" for i in range(n_genes)],
            columns=["CELL_0"],
        )

        csv_file = temp_dir / "single_cell.csv"
        df.to_csv(csv_file)

        result = await validation_service.validate_csv_tsv(csv_file, "csv")

        assert result.is_valid is True
        assert result.metadata.cell_count == 1
        assert result.metadata.gene_count == n_genes


class TestValidateFile:
    """Tests for the main validate_file method."""

    @pytest.mark.asyncio
    async def test_validate_file_nonexistent(self, validation_service, temp_dir):
        """Test validation of nonexistent file."""
        result = await validation_service.validate_file(temp_dir / "nonexistent.h5ad", "h5ad")

        assert result.is_valid is False
        assert "File not found" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_file_unsupported_format(self, validation_service, temp_dir):
        """Test validation with unsupported format."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        result = await validation_service.validate_file(test_file, "unsupported")

        assert result.is_valid is False
        assert "Unsupported file format" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_file_h5ad(self, validation_service, temp_dir):
        """Test validate_file with h5ad format."""
        import anndata as ad

        # Enable writing nullable strings for anndata >= 0.11
        ad.settings.allow_write_nullable_strings = True

        adata = ad.AnnData(X=np.random.rand(50, 30))
        h5ad_file = temp_dir / "test.h5ad"
        adata.write_h5ad(h5ad_file)

        result = await validation_service.validate_file(h5ad_file, "h5ad")

        assert result.is_valid is True
        assert result.metadata.format == "h5ad"

    @pytest.mark.asyncio
    async def test_validate_file_csv(self, validation_service, temp_dir):
        """Test validate_file with csv format."""
        df = pd.DataFrame(
            np.random.rand(50, 30),
            index=[f"GENE_{i}" for i in range(50)],
            columns=[f"CELL_{i}" for i in range(30)],
        )
        csv_file = temp_dir / "test.csv"
        df.to_csv(csv_file)

        result = await validation_service.validate_file(csv_file, "csv")

        assert result.is_valid is True
        assert result.metadata.format == "csv"
