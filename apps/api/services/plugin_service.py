"""Plugin system for registering custom analysis steps.

Allows registration of custom analysis steps without modifying core
platform code.  Validates plugin input/output contracts against the
platform schema (JSON-Schema-like: must have "type" and "properties").
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PluginRegistration(ZernaBaseModel):
    """Full registration record for a plugin."""

    plugin_id: UUID
    name: str
    version: str
    input_contract: dict[str, Any]  # JSON Schema
    output_contract: dict[str, Any]
    registered_at: datetime


class PluginInfo(ZernaBaseModel):
    """Lightweight summary returned by list_plugins()."""

    plugin_id: UUID
    name: str
    version: str


class ContractValidationError(Exception):
    """Raised when a plugin contract violates the platform schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Contract validation failed: {errors}")


# ---------------------------------------------------------------------------
# Contract validation helpers
# ---------------------------------------------------------------------------

_REQUIRED_CONTRACT_KEYS = {"type", "properties"}


def _validate_contract(contract: dict[str, Any], label: str) -> list[str]:
    """Validate that *contract* is a valid JSON-Schema-like object.

    A valid contract must contain at least a ``"type"`` field and a
    ``"properties"`` field.  ``"properties"`` must be a non-empty dict.
    """
    errors: list[str] = []

    if not isinstance(contract, dict):
        errors.append(f"{label} must be a dict, got {type(contract).__name__}")
        return errors

    for key in _REQUIRED_CONTRACT_KEYS:
        if key not in contract:
            errors.append(f"{label} missing required key '{key}'")

    if "type" in contract and not isinstance(contract["type"], str):
        errors.append(f"{label} 'type' must be a string")

    if "properties" in contract:
        props = contract["properties"]
        if not isinstance(props, dict):
            errors.append(f"{label} 'properties' must be a dict")
        elif len(props) == 0:
            errors.append(f"{label} 'properties' must not be empty")

    return errors


# ---------------------------------------------------------------------------
# Plugin service
# ---------------------------------------------------------------------------


class PluginService:
    """In-memory plugin registry with contract validation.

    For production use the store would be backed by a database; the
    in-memory dict keeps the implementation minimal and testable.
    """

    def __init__(self) -> None:
        self._plugins: dict[UUID, PluginRegistration] = {}

    def register(self, plugin_def: dict[str, Any]) -> PluginRegistration:
        """Register a new plugin after validating its contracts.

        Parameters
        ----------
        plugin_def:
            Must contain ``name`` (str), ``version`` (str),
            ``input_contract`` (dict) and ``output_contract`` (dict).

        Returns
        -------
        PluginRegistration on success.

        Raises
        ------
        ContractValidationError
            If either contract violates the platform schema.
        ValueError
            If required fields are missing from *plugin_def*.
        """
        # --- basic field validation ---
        for field in ("name", "version", "input_contract", "output_contract"):
            if field not in plugin_def:
                raise ValueError(f"plugin_def missing required field '{field}'")

        name: str = plugin_def["name"]
        version: str = plugin_def["version"]
        input_contract: dict[str, Any] = plugin_def["input_contract"]
        output_contract: dict[str, Any] = plugin_def["output_contract"]

        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' must be a non-empty string")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("'version' must be a non-empty string")

        # --- contract validation ---
        errors: list[str] = []
        errors.extend(_validate_contract(input_contract, "input_contract"))
        errors.extend(_validate_contract(output_contract, "output_contract"))

        if errors:
            raise ContractValidationError(errors)

        # --- persist ---
        registration = PluginRegistration(
            plugin_id=uuid4(),
            name=name.strip(),
            version=version.strip(),
            input_contract=input_contract,
            output_contract=output_contract,
            registered_at=datetime.now(UTC),
        )
        self._plugins[registration.plugin_id] = registration
        return registration

    def list_plugins(self) -> list[PluginInfo]:
        """Return lightweight info for every registered plugin."""
        return [
            PluginInfo(
                plugin_id=reg.plugin_id,
                name=reg.name,
                version=reg.version,
            )
            for reg in self._plugins.values()
        ]

    def get_plugin(self, plugin_id: UUID) -> PluginRegistration | None:
        """Retrieve a full registration by *plugin_id*, or ``None``."""
        return self._plugins.get(plugin_id)
