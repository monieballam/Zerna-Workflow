"""Property-based tests for file format validation.

**Validates: Requirements 2.1, 2.3**
"""

import gzip
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from scipy.io import mmwrite
from scipy.sparse import csr_matrix

from apps.api.services.file_validation_service import (
    FileValidationService,
)


# Custom strategies for generating valid test data
@st.composite
def valid_h5ad_data(draw):
    """Generate valid h5ad file data."""
    n_obs = draw(st.integers(min_value=10, max_value=500))
    n_vars = draw(st.integers(min_value=5, max_value=200))
    return {"n_obs": n_obs, "n_vars": n_vars}


@st.composite
def valid_10x_h5_data(draw):
    """Generate valid 10x h5 file data."""
    n_genes = draw(st.integers(min_value=10, max_value=500))
    n_cells = draw(st.integers(min_value=5, max_value=200))
    nnz = draw(st.integers(min_value=50, max_value=min(n_genes * n_cells, 5000)))
    return {"n_genes": n_genes, "n_cells": n_cells, "nnz": nnz}


@st.composite
def valid_10x_mtx_data(draw):
    """Generate valid 10x mtx file data."""
    n_genes = draw(st.integers(min_value=10, max_value=300))
    n_cells = draw(st.integers(min_value=5, max_value=150))
    use_gzip = draw(st.booleans())
    use_features = draw(st.booleans())  # features.tsv vs genes.tsv
    return {
        "n_genes": n_genes,
        "n_cells": n_cells,
        "use_gzip": use_gzip,
        "use_features": use_features,
    }


@st.composite
def valid_csv_tsv_data(draw):
    """Generate valid CSV/TSV file data."""
    n_genes = draw(st.integers(min_value=10, max_value=300))
    n_cells = draw(st.integers(min_value=1, max_value=150))
    file_format = draw(st.sampled_from(["csv", "tsv"]))
    return {"n_genes": n_genes, "n_cells": n_cells, "format": file_format}


@st.composite
def invalid_file_scenario(draw):
    """Generate scenarios for invalid files."""
    scenario = draw(
        st.sampled_from(
            [
                "nonexistent",
                "unsupported_format",
                "h5ad_missing_x",
                "10x_h5_missing_matrix",
                "10x_mtx_missing_files",
                "10x_mtx_count_mismatch",
                "csv_empty",
            ]
        )
    )
    return scenario


@pytest.fixture
def validation_service():
    """Create a FileValidationService instance."""
    return FileValidationService()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestFileFormatValidationProperty:
    """Property-based tests for file format validation.

    Property 5: File Format Validation
    For any uploaded file, if the file format is one of the supported types
    (h5ad, 10x h5, 10x mtx, csv, tsv) and is well-formed, it should be accepted;
    otherwise, a descriptive error should be returned.
    """

    @pytest.mark.asyncio
    @given(data=valid_h5ad_data())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_valid_h5ad_files_accepted(self, data, validation_service, temp_dir):
        """Property: Any well-formed h5ad file should be accepted and return correct metadata.

        **Validates: Requirements 2.1, 2.3**
        """
        import anndata as ad

        # Enable writing nullable strings for anndata >= 0.11
        ad.settings.allow_write_nullable_strings = True

        n_obs = data["n_obs"]
        n_vars = data["n_vars"]

        # Create valid h5ad file
        X = np.random.rand(n_obs, n_vars)
        obs = pd.DataFrame({"cell_type": ["A"] * n_obs}, index=[f"cell_{i}" for i in range(n_obs)])
        var = pd.DataFrame(
            {"gene_name": [f"gene_{i}" for i in range(n_vars)]},
            index=[f"gene_{i}" for i in range(n_vars)],
        )
        adata = ad.AnnData(X=X, obs=obs, var=var)

        h5ad_file = temp_dir / f"test_{n_obs}_{n_vars}.h5ad"
        adata.write_h5ad(h5ad_file)

        # Validate
        result = await validation_service.validate_file(h5ad_file, "h5ad")

        # Property assertions
        assert result.is_valid is True, (
            f"Valid h5ad file should be accepted: {result.error_message}"
        )
        assert result.error_message is None, "Valid file should have no error message"
        assert result.metadata is not None, "Valid file should have metadata"
        assert result.metadata.cell_count == n_obs, (
            f"Cell count should match: expected {n_obs}, got {result.metadata.cell_count}"
        )
        assert result.metadata.gene_count == n_vars, (
            f"Gene count should match: expected {n_vars}, got {result.metadata.gene_count}"
        )
        assert result.metadata.format == "h5ad", "Format should be h5ad"

    @pytest.mark.asyncio
    @given(data=valid_10x_h5_data())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_valid_10x_h5_files_accepted(self, data, validation_service, temp_dir):
        """Property: Any well-formed 10x h5 file should be accepted and return correct metadata.

        **Validates: Requirements 2.1, 2.3**
        """
        import h5py

        n_genes = data["n_genes"]
        n_cells = data["n_cells"]
        nnz = data["nnz"]

        # Create valid 10x h5 file
        h5_file = temp_dir / f"test_{n_genes}_{n_cells}.h5"
        with h5py.File(h5_file, "w") as f:
            matrix_group = f.create_group("matrix")

            # Create sparse matrix data
            data_array = np.random.rand(nnz)
            indices = np.random.randint(0, n_genes, nnz)
            indptr = np.sort(np.random.randint(0, nnz + 1, n_cells + 1))
            indptr[0] = 0
            indptr[-1] = nnz

            matrix_group.create_dataset("data", data=data_array)
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

        # Validate
        result = await validation_service.validate_file(h5_file, "10x_h5")

        # Property assertions
        assert result.is_valid is True, (
            f"Valid 10x h5 file should be accepted: {result.error_message}"
        )
        assert result.error_message is None, "Valid file should have no error message"
        assert result.metadata is not None, "Valid file should have metadata"
        assert result.metadata.cell_count == n_cells, (
            f"Cell count should match: expected {n_cells}, got {result.metadata.cell_count}"
        )
        assert result.metadata.gene_count == n_genes, (
            f"Gene count should match: expected {n_genes}, got {result.metadata.gene_count}"
        )
        assert result.metadata.format == "10x_h5", "Format should be 10x_h5"

    @pytest.mark.asyncio
    @given(data=valid_10x_mtx_data())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_valid_10x_mtx_files_accepted(self, data, validation_service, temp_dir):
        """Property: Any well-formed 10x mtx directory should be accepted and return correct metadata.

        **Validates: Requirements 2.1, 2.3**
        """
        n_genes = data["n_genes"]
        n_cells = data["n_cells"]
        use_gzip = data["use_gzip"]
        use_features = data["use_features"]

        # Create a unique subdirectory for this test iteration to avoid conflicts
        import uuid

        test_subdir = temp_dir / str(uuid.uuid4())
        test_subdir.mkdir(parents=True, exist_ok=True)

        # Create matrix
        matrix = csr_matrix(np.random.rand(n_genes, n_cells))

        if use_gzip:
            matrix_file = test_subdir / "matrix.mtx.gz"
            with gzip.open(matrix_file, "wb") as f:
                mmwrite(f, matrix)
        else:
            matrix_file = test_subdir / "matrix.mtx"
            mmwrite(matrix_file, matrix)

        # Create genes or features file
        if use_features:
            genes_file = test_subdir / ("features.tsv.gz" if use_gzip else "features.tsv")
        else:
            genes_file = test_subdir / ("genes.tsv.gz" if use_gzip else "genes.tsv")

        if use_gzip:
            with gzip.open(genes_file, "wt") as f:
                for i in range(n_genes):
                    f.write(f"GENE_{i}\tGene_{i}\n")
        else:
            with open(genes_file, "w") as f:
                for i in range(n_genes):
                    f.write(f"GENE_{i}\tGene_{i}\n")

        # Create barcodes file
        barcodes_file = test_subdir / ("barcodes.tsv.gz" if use_gzip else "barcodes.tsv")
        if use_gzip:
            with gzip.open(barcodes_file, "wt") as f:
                for i in range(n_cells):
                    f.write(f"CELL_{i}\n")
        else:
            with open(barcodes_file, "w") as f:
                for i in range(n_cells):
                    f.write(f"CELL_{i}\n")

        # Validate
        result = await validation_service.validate_file(test_subdir, "10x_mtx")

        # Property assertions
        assert result.is_valid is True, (
            f"Valid 10x mtx directory should be accepted: {result.error_message}"
        )
        assert result.error_message is None, "Valid file should have no error message"
        assert result.metadata is not None, "Valid file should have metadata"
        assert result.metadata.cell_count == n_cells, (
            f"Cell count should match: expected {n_cells}, got {result.metadata.cell_count}"
        )
        assert result.metadata.gene_count == n_genes, (
            f"Gene count should match: expected {n_genes}, got {result.metadata.gene_count}"
        )
        assert result.metadata.format == "10x_mtx", "Format should be 10x_mtx"

    @pytest.mark.asyncio
    @given(data=valid_csv_tsv_data())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_valid_csv_tsv_files_accepted(self, data, validation_service, temp_dir):
        """Property: Any well-formed CSV/TSV file should be accepted and return correct metadata.

        **Validates: Requirements 2.1, 2.3**
        """
        n_genes = data["n_genes"]
        n_cells = data["n_cells"]
        file_format = data["format"]

        # Create CSV/TSV file
        expression_data = np.random.rand(n_genes, n_cells)
        df = pd.DataFrame(
            expression_data,
            index=[f"GENE_{i}" for i in range(n_genes)],
            columns=[f"CELL_{i}" for i in range(n_cells)],
        )

        file_path = temp_dir / f"expression.{file_format}"
        if file_format == "csv":
            df.to_csv(file_path)
        else:
            df.to_csv(file_path, sep="\t")

        # Validate
        result = await validation_service.validate_file(file_path, file_format)

        # Property assertions
        assert result.is_valid is True, (
            f"Valid {file_format} file should be accepted: {result.error_message}"
        )
        assert result.error_message is None, "Valid file should have no error message"
        assert result.metadata is not None, "Valid file should have metadata"
        assert result.metadata.cell_count == n_cells, (
            f"Cell count should match: expected {n_cells}, got {result.metadata.cell_count}"
        )
        assert result.metadata.gene_count == n_genes, (
            f"Gene count should match: expected {n_genes}, got {result.metadata.gene_count}"
        )
        assert result.metadata.format == file_format, f"Format should be {file_format}"

    @pytest.mark.asyncio
    @given(scenario=invalid_file_scenario())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_invalid_files_rejected_with_descriptive_error(
        self, scenario, validation_service, temp_dir
    ):
        """Property: Any invalid or malformed file should be rejected with a descriptive error message.

        **Validates: Requirements 2.1, 2.3**
        """
        result = None

        if scenario == "nonexistent":
            # Test nonexistent file
            result = await validation_service.validate_file(temp_dir / "nonexistent.h5ad", "h5ad")

        elif scenario == "unsupported_format":
            # Test unsupported format
            test_file = temp_dir / "test.txt"
            test_file.write_text("test content")
            result = await validation_service.validate_file(test_file, "unsupported")

        elif scenario == "h5ad_missing_x":
            # Test h5ad file missing X matrix
            import h5py

            h5ad_file = temp_dir / "invalid.h5ad"
            with h5py.File(h5ad_file, "w") as f:
                f.create_dataset("obs", data=[1, 2, 3])
            result = await validation_service.validate_file(h5ad_file, "h5ad")

        elif scenario == "10x_h5_missing_matrix":
            # Test 10x h5 file missing matrix group
            import h5py

            h5_file = temp_dir / "invalid_10x.h5"
            with h5py.File(h5_file, "w") as f:
                f.create_dataset("data", data=[1, 2, 3])
            result = await validation_service.validate_file(h5_file, "10x_h5")

        elif scenario == "10x_mtx_missing_files":
            # Test 10x mtx with missing files (only matrix)
            matrix = csr_matrix(np.random.rand(50, 25))
            matrix_file = temp_dir / "matrix.mtx"
            mmwrite(matrix_file, matrix)
            result = await validation_service.validate_file(temp_dir, "10x_mtx")

        elif scenario == "10x_mtx_count_mismatch":
            # Test 10x mtx with mismatched counts
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

            result = await validation_service.validate_file(temp_dir, "10x_mtx")

        elif scenario == "csv_empty":
            # Test empty CSV file
            csv_file = temp_dir / "empty.csv"
            csv_file.write_text("")
            result = await validation_service.validate_file(csv_file, "csv")

        # Property assertions
        assert result is not None, f"Result should not be None for scenario: {scenario}"
        assert result.is_valid is False, f"Invalid file should be rejected for scenario: {scenario}"
        assert result.error_message is not None, (
            f"Invalid file should have error message for scenario: {scenario}"
        )
        assert len(result.error_message) > 0, (
            f"Error message should be descriptive for scenario: {scenario}"
        )
        assert result.metadata is None, (
            f"Invalid file should not have metadata for scenario: {scenario}"
        )

    @pytest.mark.asyncio
    @given(
        n_obs=st.integers(min_value=1, max_value=1000),
        n_vars=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_metadata_extraction_accuracy(
        self, n_obs, n_vars, validation_service, temp_dir
    ):
        """Property: For any valid file, extracted metadata (cell count, gene count) should match the actual data.

        **Validates: Requirements 2.1, 2.3**
        """
        import anndata as ad

        # Enable writing nullable strings for anndata >= 0.11
        ad.settings.allow_write_nullable_strings = True

        # Create h5ad file with specific dimensions
        X = np.random.rand(n_obs, n_vars)
        adata = ad.AnnData(X=X)

        h5ad_file = temp_dir / f"metadata_test_{n_obs}_{n_vars}.h5ad"
        adata.write_h5ad(h5ad_file)

        # Validate and extract metadata
        result = await validation_service.validate_file(h5ad_file, "h5ad")

        # Property assertions: metadata must exactly match the input dimensions
        assert result.is_valid is True, "File should be valid"
        assert result.metadata is not None, "Metadata should be extracted"
        assert result.metadata.cell_count == n_obs, (
            f"Extracted cell count must match actual: expected {n_obs}, got {result.metadata.cell_count}"
        )
        assert result.metadata.gene_count == n_vars, (
            f"Extracted gene count must match actual: expected {n_vars}, got {result.metadata.gene_count}"
        )
