"""Shared enumerations for Zerna platform."""

from enum import Enum


class UserRole(str, Enum):
    """User roles for role-based access control."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class RunStatus(str, Enum):
    """Status of a pipeline run execution."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactType(str, Enum):
    """Types of artifacts produced by pipeline runs."""

    H5AD = "h5ad"
    EMBEDDING_PLOT = "embedding_plot"
    QC_REPORT = "qc_report"
    DE_RESULTS = "de_results"
    PATHWAY_SCORES = "pathway_scores"
    LIANA_RESULTS = "liana_results"


class KnowledgePackType(str, Enum):
    """Types of knowledge packs for reference data."""

    CELL_TYPE_MARKERS = "cell_type_markers"
    PATHWAY_DATABASE = "pathway_database"
    LIGAND_RECEPTOR_PAIRS = "ligand_receptor_pairs"


class ErrorType(str, Enum):
    """Error classification for retry behavior."""

    USER_ERROR = "user_error"
    SYSTEM_ERROR = "system_error"
    TRANSIENT_ERROR = "transient_error"


class SortOrder(str, Enum):
    """Sort order for list queries."""

    ASC = "asc"
    DESC = "desc"


class ComputePreference(str, Enum):
    """Compute resource preference for method execution."""

    CPU_ONLY = "cpu_only"
    GPU_PREFERRED = "gpu_preferred"
    GPU_REQUIRED = "gpu_required"


class ComputeBackend(str, Enum):
    """Available compute backends for heterogeneous execution."""

    CUDA = "cuda"
    ROCM = "rocm"
    METAL = "metal"
    OPENCL = "opencl"
    TPU = "tpu"
    CPU = "cpu"
