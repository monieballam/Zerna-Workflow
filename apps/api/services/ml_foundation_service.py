"""ML Foundation layer for model versioning and inference provenance.

Manages model versioning, inference provenance, and metadata storage.
Records model version, input hash, and inference timestamp for every
inference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ModelRecord(ZernaBaseModel):
    """A registered ML model with versioning metadata."""

    model_id: UUID
    name: str
    version: str
    metadata: dict[str, Any]
    registered_at: datetime


class InferenceLog(ZernaBaseModel):
    """Provenance record for a single ML inference."""

    inference_id: UUID
    model_id: UUID
    model_version: str
    input_hash: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# ML Foundation Service
# ---------------------------------------------------------------------------


class MLFoundationService:
    """In-memory ML model registry with inference provenance logging.

    For production the stores would be backed by a database; the
    in-memory dicts keep the implementation minimal and testable.
    """

    def __init__(self) -> None:
        self._models: dict[UUID, ModelRecord] = {}
        self._inferences: dict[UUID, InferenceLog] = {}

    # -- model registration -------------------------------------------------

    def register_model(self, metadata: dict[str, Any]) -> ModelRecord:
        """Register a new ML model.

        Parameters
        ----------
        metadata:
            Must contain ``name`` (str), ``version`` (str), and
            optionally any extra key-value pairs stored as model
            metadata.

        Returns
        -------
        ModelRecord on success.

        Raises
        ------
        ValueError
            If required fields are missing or invalid.
        """
        for field in ("name", "version"):
            if field not in metadata:
                raise ValueError(f"metadata missing required field '{field}'")

        name: str = metadata["name"]
        version: str = metadata["version"]

        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' must be a non-empty string")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("'version' must be a non-empty string")

        # Extra metadata is everything except name/version
        extra = {k: v for k, v in metadata.items() if k not in ("name", "version")}

        record = ModelRecord(
            model_id=uuid4(),
            name=name.strip(),
            version=version.strip(),
            metadata=extra,
            registered_at=datetime.now(UTC),
        )
        self._models[record.model_id] = record
        return record

    def get_model(self, model_id: UUID) -> ModelRecord | None:
        """Retrieve a model record by *model_id*, or ``None``."""
        return self._models.get(model_id)

    # -- inference provenance -----------------------------------------------

    def log_inference(self, model_id: UUID, input_hash: str) -> InferenceLog:
        """Log an inference event for a registered model.

        Parameters
        ----------
        model_id:
            The UUID of a previously registered model.
        input_hash:
            A hash of the inference input data.

        Returns
        -------
        InferenceLog with provenance fields populated.

        Raises
        ------
        ValueError
            If *model_id* is not registered or *input_hash* is empty.
        """
        model = self._models.get(model_id)
        if model is None:
            raise ValueError(f"No model registered with id {model_id}")

        if not isinstance(input_hash, str) or not input_hash.strip():
            raise ValueError("'input_hash' must be a non-empty string")

        log = InferenceLog(
            inference_id=uuid4(),
            model_id=model_id,
            model_version=model.version,
            input_hash=input_hash.strip(),
            timestamp=datetime.now(UTC),
        )
        self._inferences[log.inference_id] = log
        return log

    def get_inference(self, inference_id: UUID) -> InferenceLog | None:
        """Retrieve an inference log by *inference_id*, or ``None``."""
        return self._inferences.get(inference_id)
