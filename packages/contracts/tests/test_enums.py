"""Tests for shared enumerations."""

from zerna_contracts import (
    ArtifactType,
    ComputeBackend,
    ComputePreference,
    ErrorType,
    KnowledgePackType,
    RunStatus,
    SortOrder,
    UserRole,
)


class TestEnums:
    """Test suite for shared enums."""

    def test_user_role_values(self):
        """Test UserRole enum has correct values."""
        assert UserRole.ADMIN == "admin"
        assert UserRole.MEMBER == "member"
        assert UserRole.VIEWER == "viewer"
        assert len(list(UserRole)) == 3

    def test_run_status_values(self):
        """Test RunStatus enum has correct values."""
        assert RunStatus.QUEUED == "queued"
        assert RunStatus.RUNNING == "running"
        assert RunStatus.COMPLETED == "completed"
        assert RunStatus.FAILED == "failed"
        assert RunStatus.CANCELLED == "cancelled"
        assert len(list(RunStatus)) == 5

    def test_artifact_type_values(self):
        """Test ArtifactType enum has correct values."""
        assert ArtifactType.H5AD == "h5ad"
        assert ArtifactType.EMBEDDING_PLOT == "embedding_plot"
        assert ArtifactType.QC_REPORT == "qc_report"
        assert ArtifactType.DE_RESULTS == "de_results"
        assert ArtifactType.PATHWAY_SCORES == "pathway_scores"
        assert ArtifactType.LIANA_RESULTS == "liana_results"
        assert len(list(ArtifactType)) == 6

    def test_knowledge_pack_type_values(self):
        """Test KnowledgePackType enum has correct values."""
        assert KnowledgePackType.CELL_TYPE_MARKERS == "cell_type_markers"
        assert KnowledgePackType.PATHWAY_DATABASE == "pathway_database"
        assert KnowledgePackType.LIGAND_RECEPTOR_PAIRS == "ligand_receptor_pairs"
        assert len(list(KnowledgePackType)) == 3

    def test_error_type_values(self):
        """Test ErrorType enum has correct values."""
        assert ErrorType.USER_ERROR == "user_error"
        assert ErrorType.SYSTEM_ERROR == "system_error"
        assert ErrorType.TRANSIENT_ERROR == "transient_error"
        assert len(list(ErrorType)) == 3

    def test_sort_order_values(self):
        """Test SortOrder enum has correct values."""
        assert SortOrder.ASC == "asc"
        assert SortOrder.DESC == "desc"
        assert len(list(SortOrder)) == 2

    def test_compute_preference_values(self):
        """Test ComputePreference enum has correct values."""
        assert ComputePreference.CPU_ONLY == "cpu_only"
        assert ComputePreference.GPU_PREFERRED == "gpu_preferred"
        assert ComputePreference.GPU_REQUIRED == "gpu_required"
        assert len(list(ComputePreference)) == 3

    def test_compute_backend_values(self):
        """Test ComputeBackend enum has correct values."""
        assert ComputeBackend.CUDA == "cuda"
        assert ComputeBackend.ROCM == "rocm"
        assert ComputeBackend.METAL == "metal"
        assert ComputeBackend.OPENCL == "opencl"
        assert ComputeBackend.TPU == "tpu"
        assert ComputeBackend.CPU == "cpu"
        assert len(list(ComputeBackend)) == 6
