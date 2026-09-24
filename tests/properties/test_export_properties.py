"""Property-based tests for export format support and reproducibility report completeness.

# Feature: gap-analysis-and-verification, Property 9: Export format support and reproducibility report completeness

**Validates: Requirements 6.2, 6.3**
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from zerna_contracts.base import ZernaBaseModel
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Lightweight export models (mirrors export_service.py logic without DB/S3)
# ---------------------------------------------------------------------------

SUPPORTED_DATA_FORMATS = {"h5ad", "csv", "seurat"}


class ReproducibilityReport(ZernaBaseModel):
    """Reproducibility report attached to every export."""

    run_manifest: dict[str, Any]
    parameter_provenance: dict[str, Any]
    method_versions: dict[str, str]


class ExportArtifact(ZernaBaseModel):
    """Result of an export operation."""

    run_id: UUID
    format: str
    artifact_path: str
    reproducibility_report: ReproducibilityReport


class ExportRequest(ZernaBaseModel):
    """Input to the export service."""

    run_id: UUID
    org_id: UUID
    format: Literal["h5ad", "csv", "seurat"]
    parameters: dict[str, Any] = {}
    method_versions: dict[str, str] = {}
    dataset_version_id: UUID | None = None
    random_seed: int | None = None


def perform_export(request: ExportRequest) -> ExportArtifact:
    """Pure-function export that produces an artifact with reproducibility report.

    This mirrors the core logic of ExportService without I/O dependencies.
    For any supported format, it produces a valid artifact and a complete
    reproducibility report containing run_manifest, parameter_provenance,
    and method_versions.
    """
    if request.format not in SUPPORTED_DATA_FORMATS:
        raise ValueError(f"Unsupported format: {request.format}")

    # Build reproducibility report
    run_manifest = {
        "run_id": str(request.run_id),
        "org_id": str(request.org_id),
        "dataset_version_id": str(request.dataset_version_id)
        if request.dataset_version_id
        else None,
        "random_seed": request.random_seed,
        "exported_at": datetime.now(UTC).isoformat(),
    }

    parameter_provenance = {
        "parameters": request.parameters,
        "source": "run_manifest",
    }

    report = ReproducibilityReport(
        run_manifest=run_manifest,
        parameter_provenance=parameter_provenance,
        method_versions=request.method_versions,
    )

    # Determine artifact path based on format
    ext_map = {"h5ad": "export.h5ad", "csv": "cell_metadata.csv", "seurat": "seurat/manifest.json"}
    artifact_path = f"{request.org_id}/exports/{request.run_id}/{ext_map[request.format]}"

    return ExportArtifact(
        run_id=request.run_id,
        format=request.format,
        artifact_path=artifact_path,
        reproducibility_report=report,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_uuid_st = st.builds(uuid4)

_export_format = st.sampled_from(["h5ad", "csv", "seurat"])

_parameters = st.dictionaries(
    keys=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    values=st.one_of(
        st.integers(min_value=0, max_value=10000),
        st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        st.text(min_size=1, max_size=20),
    ),
    min_size=0,
    max_size=10,
)

_method_versions = st.dictionaries(
    keys=st.sampled_from(
        ["qc", "normalize", "hvg", "pca", "cluster", "annotate", "de", "integration"]
    ),
    values=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
    min_size=0,
    max_size=8,
)

_random_seed = st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1))

_export_request = st.builds(
    ExportRequest,
    run_id=_uuid_st,
    org_id=_uuid_st,
    format=_export_format,
    parameters=_parameters,
    method_versions=_method_versions,
    dataset_version_id=st.one_of(st.none(), _uuid_st),
    random_seed=_random_seed,
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestExportFormatSupportAndReproducibilityReport:
    """Property 9: Export format support and reproducibility report completeness.

    For any export request with format in {h5ad, csv, seurat}, the export
    service must produce a valid artifact. Every export must include a
    reproducibility report containing run_manifest, parameter_provenance,
    and method_versions fields.
    """

    @given(request=_export_request)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_export_produces_valid_artifact_for_supported_formats(
        self, request: ExportRequest
    ) -> None:
        """For any supported format, export must produce a valid artifact."""
        result = perform_export(request)

        # Artifact must reference the correct run
        assert result.run_id == request.run_id

        # Artifact format must match request
        assert result.format == request.format
        assert result.format in SUPPORTED_DATA_FORMATS

        # Artifact path must be non-empty and contain the run_id
        assert len(result.artifact_path) > 0
        assert str(request.run_id) in result.artifact_path

    @given(request=_export_request)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_reproducibility_report_contains_required_fields(self, request: ExportRequest) -> None:
        """Every export must include a reproducibility report with run_manifest,
        parameter_provenance, and method_versions."""
        result = perform_export(request)
        report = result.reproducibility_report

        # run_manifest must be present and non-empty
        assert report.run_manifest is not None
        assert isinstance(report.run_manifest, dict)
        assert "run_id" in report.run_manifest
        assert report.run_manifest["run_id"] == str(request.run_id)

        # parameter_provenance must be present
        assert report.parameter_provenance is not None
        assert isinstance(report.parameter_provenance, dict)
        assert "parameters" in report.parameter_provenance

        # method_versions must be present
        assert report.method_versions is not None
        assert isinstance(report.method_versions, dict)

    @given(request=_export_request)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_reproducibility_report_preserves_method_versions(self, request: ExportRequest) -> None:
        """Method versions in the report must match those from the request."""
        result = perform_export(request)
        report = result.reproducibility_report

        # Every method version from the request must appear in the report
        for method, version in request.method_versions.items():
            assert method in report.method_versions
            assert report.method_versions[method] == version

    @given(request=_export_request)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_reproducibility_report_preserves_parameters(self, request: ExportRequest) -> None:
        """Parameter provenance must contain the original parameters."""
        result = perform_export(request)
        report = result.reproducibility_report

        stored_params = report.parameter_provenance.get("parameters", {})
        for key, value in request.parameters.items():
            assert key in stored_params
            assert stored_params[key] == value

    @given(fmt=st.sampled_from(["h5ad", "csv", "seurat"]))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_supported_formats_produce_artifacts(self, fmt: str) -> None:
        """Each supported format must produce a valid artifact without error."""
        request = ExportRequest(
            run_id=uuid4(),
            org_id=uuid4(),
            format=fmt,
            parameters={"resolution": 0.5},
            method_versions={"qc": "1.0.0"},
        )
        result = perform_export(request)
        assert result.format == fmt
        assert result.reproducibility_report is not None
        assert "run_id" in result.reproducibility_report.run_manifest
        assert "parameters" in result.reproducibility_report.parameter_provenance
