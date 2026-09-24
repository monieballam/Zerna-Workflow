"""Run manifest contract for immutable run binding."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from .base import ZernaBaseModel


class RunManifest(ZernaBaseModel):
    """Immutable record of all parameters, dataset versions, and method versions
    used in a single pipeline execution.

    This contract ensures every run is explicitly and immutably linked to a
    specific dataset version, supporting reproducibility and provenance tracking.
    """

    run_id: UUID = Field(description="Unique identifier for the run")
    dataset_version_id: UUID = Field(description="ID of the dataset version bound to this run")
    dataset_checksum: str = Field(
        min_length=1,
        description="SHA-256 checksum of the dataset version's source files",
    )
    template_id: UUID = Field(description="Pipeline template used for this run")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Run parameters validated against template schema",
    )
    method_versions: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of step_name to method version string",
    )
    random_seed: int | None = Field(default=None, description="Random seed for reproducibility")
    created_at: datetime = Field(description="Timestamp when the manifest was created")
