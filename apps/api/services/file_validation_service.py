"""File validation service for single-cell data formats.

Validates and extracts metadata from h5ad, 10x h5, 10x mtx, csv, and tsv formats.
"""

import bz2
import gzip
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel, Field


class FileMetadata(BaseModel):
    """Metadata extracted from a valid file."""

    cell_count: int
    gene_count: int
    format: str
    additional_metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Result of file validation."""

    is_valid: bool
    error_message: str | None = None
    metadata: FileMetadata | None = None


class FileValidationService:
    """Service for validating single-cell data files and extracting metadata."""

    def __init__(self) -> None:
        """Initialize FileValidationService."""
        pass

    async def validate_file(self, file_path: str | Path, file_format: str) -> ValidationResult:
        """Validate a file and extract metadata.

        Args:
            file_path: Path to the file to validate
            file_format: Expected format (h5ad, 10x_h5, 10x_mtx, csv, tsv)

        Returns:
            ValidationResult with validation status and metadata
        """
        file_path = Path(file_path)

        if not file_path.exists():
            return ValidationResult(is_valid=False, error_message=f"File not found: {file_path}")

        try:
            if file_format == "h5ad":
                return await self.validate_h5ad(file_path)
            elif file_format == "10x_h5":
                return await self.validate_10x_h5(file_path)
            elif file_format == "10x_mtx":
                return await self.validate_10x_mtx(file_path)
            elif file_format in ["csv", "tsv"]:
                return await self.validate_csv_tsv(file_path, file_format)
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Unsupported file format: {file_format}. "
                        "Supported formats: h5ad, 10x_h5, 10x_mtx, csv, tsv"
                    ),
                )
        except Exception as e:
            return ValidationResult(is_valid=False, error_message=f"Validation error: {str(e)}")

    async def validate_h5ad(self, file_path: Path) -> ValidationResult:
        """Validate h5ad file format and extract metadata.

        Args:
            file_path: Path to h5ad file

        Returns:
            ValidationResult with validation status and metadata
        """
        try:
            import anndata as ad
            import h5py
        except ImportError:
            return ValidationResult(
                is_valid=False,
                error_message="Required libraries not installed: anndata, h5py",
            )

        try:
            # First check if it's a valid HDF5 file
            with h5py.File(file_path, "r") as f:
                # Check for required AnnData structure
                if "X" not in f:
                    return ValidationResult(
                        is_valid=False,
                        error_message="Invalid h5ad file: missing 'X' (expression matrix)",
                    )

            # Validate structure in backed mode so large H5AD uploads do not materialize
            # the entire expression matrix in memory during metadata extraction.
            adata = ad.read_h5ad(file_path, backed="r")
            try:
                # Extract metadata
                cell_count = adata.n_obs
                gene_count = adata.n_vars

                additional_metadata = {
                    "obs_columns": list(adata.obs.columns),
                    "var_columns": list(adata.var.columns),
                    "layers": list(adata.layers.keys()) if adata.layers else [],
                    "obsm_keys": list(adata.obsm.keys()) if adata.obsm else [],
                    "varm_keys": list(adata.varm.keys()) if adata.varm else [],
                }
            finally:
                if getattr(adata, "file", None) is not None:
                    adata.file.close()

            return ValidationResult(
                is_valid=True,
                metadata=FileMetadata(
                    cell_count=cell_count,
                    gene_count=gene_count,
                    format="h5ad",
                    additional_metadata=additional_metadata,
                ),
            )

        except Exception as e:
            return ValidationResult(is_valid=False, error_message=f"Invalid h5ad file: {str(e)}")

    async def validate_10x_h5(self, file_path: Path) -> ValidationResult:
        """Validate 10x HDF5 file format and extract metadata.

        Args:
            file_path: Path to 10x h5 file

        Returns:
            ValidationResult with validation status and metadata
        """
        try:
            import h5py
        except ImportError:
            return ValidationResult(
                is_valid=False, error_message="Required library not installed: h5py"
            )

        try:
            with h5py.File(file_path, "r") as f:
                # 10x h5 files have a specific structure
                # Check for matrix group
                if "matrix" not in f:
                    return ValidationResult(
                        is_valid=False,
                        error_message="Invalid 10x h5 file: missing 'matrix' group",
                    )

                matrix_group = f["matrix"]

                # Check for required datasets
                required_keys = ["barcodes", "data", "indices", "indptr", "shape"]
                missing_keys = [key for key in required_keys if key not in matrix_group]

                if missing_keys:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Invalid 10x h5 file: missing required keys: {missing_keys}",
                    )

                # Extract shape
                shape = matrix_group["shape"][:]
                gene_count = int(shape[0])
                cell_count = int(shape[1])

                # Check for features (genes)
                features_group = matrix_group.get("features", None)
                if features_group is None:
                    # Try alternative location
                    if "genes" in matrix_group:
                        features_group = matrix_group["genes"]

                additional_metadata: dict[str, Any] = {}
                if features_group:
                    additional_metadata["has_features"] = True
                    if "name" in features_group:
                        additional_metadata["feature_count"] = len(features_group["name"])

                return ValidationResult(
                    is_valid=True,
                    metadata=FileMetadata(
                        cell_count=cell_count,
                        gene_count=gene_count,
                        format="10x_h5",
                        additional_metadata=additional_metadata,
                    ),
                )

        except Exception as e:
            return ValidationResult(is_valid=False, error_message=f"Invalid 10x h5 file: {str(e)}")

    async def validate_10x_mtx(self, file_path: Path) -> ValidationResult:
        """Validate 10x MTX format (matrix.mtx, genes.tsv, barcodes.tsv).

        Args:
            file_path: Path to directory or archive containing 10x MTX files

        Returns:
            ValidationResult with validation status and metadata
        """
        try:
            from scipy.io import mmread
        except ImportError:
            return ValidationResult(
                is_valid=False, error_message="Required library not installed: scipy"
            )

        try:
            # Handle both directory and archive formats
            if file_path.is_dir():
                mtx_dir = file_path
            elif file_path.suffix in [".zip", ".tar", ".gz"]:
                # Extract to temporary directory
                temp_dir = tempfile.mkdtemp()
                if file_path.suffix == ".zip":
                    with zipfile.ZipFile(file_path, "r") as zip_ref:
                        zip_ref.extractall(temp_dir)
                elif file_path.suffix in [".tar", ".gz"]:
                    with tarfile.open(file_path, "r:*") as tar_ref:
                        tar_ref.extractall(temp_dir)
                mtx_dir = Path(temp_dir)
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message="10x MTX format requires a directory or archive (.zip, .tar, .tar.gz)",
                )

            # Look for required files
            matrix_file = None
            genes_file = None
            barcodes_file = None

            # Search in directory and subdirectories
            for file in mtx_dir.rglob("*"):
                if file.name in ["matrix.mtx", "matrix.mtx.gz"]:
                    matrix_file = file
                elif file.name in ["genes.tsv", "genes.tsv.gz", "features.tsv", "features.tsv.gz"]:
                    genes_file = file
                elif file.name in ["barcodes.tsv", "barcodes.tsv.gz"]:
                    barcodes_file = file

            # Check for required files
            missing_files = []
            if matrix_file is None:
                missing_files.append("matrix.mtx")
            if genes_file is None:
                missing_files.append("genes.tsv or features.tsv")
            if barcodes_file is None:
                missing_files.append("barcodes.tsv")

            if missing_files:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Invalid 10x MTX format: missing required files: {missing_files}",
                )
            assert matrix_file is not None
            assert genes_file is not None
            assert barcodes_file is not None

            # Read matrix to get shape
            matrix = mmread(matrix_file)
            gene_count = matrix.shape[0]
            cell_count = matrix.shape[1]

            # Count lines in genes and barcodes files
            import gzip

            def count_lines(file_path: Path) -> int:
                if file_path.suffix == ".gz":
                    with gzip.open(file_path, "rt") as f:
                        return sum(1 for _ in f)
                else:
                    with open(file_path) as f:
                        return sum(1 for _ in f)

            genes_count = count_lines(genes_file)
            barcodes_count = count_lines(barcodes_file)

            # Validate counts match matrix dimensions
            if genes_count != gene_count:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Gene count mismatch: matrix has {gene_count} genes, but genes file has {genes_count} entries",
                )

            if barcodes_count != cell_count:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Barcode count mismatch: matrix has {cell_count} cells, but barcodes file has {barcodes_count} entries",
                )

            additional_metadata = {
                "matrix_file": matrix_file.name,
                "genes_file": genes_file.name,
                "barcodes_file": barcodes_file.name,
                "nnz": int(matrix.nnz),  # Number of non-zero entries
            }

            return ValidationResult(
                is_valid=True,
                metadata=FileMetadata(
                    cell_count=cell_count,
                    gene_count=gene_count,
                    format="10x_mtx",
                    additional_metadata=additional_metadata,
                ),
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False, error_message=f"Invalid 10x MTX format: {str(e)}"
            )

    async def validate_csv_tsv(self, file_path: Path, file_format: str) -> ValidationResult:
        """Validate CSV/TSV file format and extract metadata.

        Args:
            file_path: Path to CSV/TSV file
            file_format: Either 'csv' or 'tsv'

        Returns:
            ValidationResult with validation status and metadata
        """
        try:
            import pandas as pd
        except ImportError:
            return ValidationResult(
                is_valid=False, error_message="Required library not installed: pandas"
            )

        try:
            # Determine separator
            sep = "," if file_format == "csv" else "\t"

            def open_text(path: Path) -> TextIO:
                if path.suffix == ".gz":
                    return gzip.open(path, "rt")
                if path.suffix == ".bz2":
                    return bz2.open(path, "rt")
                return open(path)

            # Read file with pandas
            # Assume first column is gene names, rest are cells
            df = pd.read_csv(file_path, sep=sep, index_col=0, nrows=5, compression="infer")

            # Check if file is empty
            if df.empty:
                # Could be a single-column file (e.g. barcodes.tsv, genes.tsv)
                # Re-read without index_col to check
                df_raw = pd.read_csv(file_path, sep=sep, header=None, nrows=5, compression="infer")
                if df_raw.empty:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Invalid {file_format} file: file is empty",
                    )
                # Accept single-column or non-matrix TSV/CSV files
                return ValidationResult(
                    is_valid=True,
                    metadata=None,
                )

            # Get full dimensions without loading entire file
            # Read first line to count columns
            with open_text(file_path) as f:
                first_line = f.readline()
                num_columns = len(first_line.split(sep))

            # Count total lines (genes)
            with open_text(file_path) as f:
                num_lines = sum(1 for _ in f)

            # Subtract header row
            gene_count = num_lines - 1
            # Subtract index column
            cell_count = num_columns - 1

            if gene_count <= 0 or cell_count <= 0:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Invalid {file_format} file: insufficient data (genes: {gene_count}, cells: {cell_count})",
                )

            additional_metadata = {
                "separator": sep,
                "has_header": True,
                "has_index": True,
            }

            return ValidationResult(
                is_valid=True,
                metadata=FileMetadata(
                    cell_count=cell_count,
                    gene_count=gene_count,
                    format=file_format,
                    additional_metadata=additional_metadata,
                ),
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False, error_message=f"Invalid {file_format} file: {str(e)}"
            )
