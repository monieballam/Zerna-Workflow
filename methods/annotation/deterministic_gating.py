"""Deterministic gating module for marker-threshold-based cell classification.

Classifies cells using marker expression thresholds from configurable YAML/JSON
marker panels. Implements hierarchy mapping for general (L1/L2/L3),
myeloid-specific, and stromal-specific (v1/v2) cell type hierarchies.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class GatingRule(ZernaBaseModel):
    """A single gating rule: marker thresholds that define a cell type."""

    rule_id: str = Field(description="Unique identifier for this gating rule")
    label: str = Field(description="Cell type label assigned when rule fires")
    markers: dict[str, float] = Field(
        description="Marker name -> threshold. Rule fires when ALL markers exceed their threshold."
    )
    priority: int = Field(
        default=0,
        description="Higher priority rules take precedence when multiple rules fire",
    )


class MarkerPanel(ZernaBaseModel):
    """A configurable marker panel with gating rules."""

    name: str = Field(description="Panel name")
    version: str = Field(description="Panel version string")
    rules: list[GatingRule] = Field(description="Ordered list of gating rules")
    default_label: str = Field(
        default="Unknown",
        description="Label assigned when no rule fires",
    )


class HierarchyEntry(ZernaBaseModel):
    """Maps a label to its position in the L1/L2/L3 hierarchy."""

    level1: str
    level2: str
    level3: str


class HierarchyMap(ZernaBaseModel):
    """A hierarchy mapping definition."""

    name: str = Field(description="Hierarchy name (e.g. 'general', 'myeloid', 'stromal_v1')")
    mapping: dict[str, HierarchyEntry] = Field(description="Label -> hierarchy entry mapping")


class GatingResult(ZernaBaseModel):
    """Result of deterministic gating classification."""

    cell_labels: dict[str, str] = Field(description="cell_id -> label")
    gating_rule_ids: dict[str, str] = Field(description="cell_id -> rule_id")
    marker_panel_version: str = Field(description="Version of the marker panel used")
    hierarchy_level: Literal["L1", "L2", "L3"] = Field(
        default="L3", description="Hierarchy level of the output labels"
    )


# ---------------------------------------------------------------------------
# Panel loading
# ---------------------------------------------------------------------------


def load_marker_panel(source: str | Path | dict[str, Any]) -> MarkerPanel:
    """Load a marker panel from a YAML file, JSON file, or dict.

    Args:
        source: Path to YAML/JSON file, or a dict with panel definition.

    Returns:
        Parsed MarkerPanel.
    """
    if isinstance(source, dict):
        data = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Marker panel file not found: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Marker panel must be a dict/object at top level")

    rules: list[GatingRule] = []
    for i, rule_data in enumerate(data.get("rules", [])):
        rules.append(
            GatingRule(
                rule_id=rule_data.get("rule_id", f"rule_{i}"),
                label=rule_data["label"],
                markers=rule_data["markers"],
                priority=rule_data.get("priority", 0),
            )
        )

    return MarkerPanel(
        name=data.get("name", "unnamed"),
        version=data.get("version", "0.0.0"),
        rules=rules,
        default_label=data.get("default_label", "Unknown"),
    )


def load_hierarchy_map(source: str | Path | dict[str, Any]) -> HierarchyMap:
    """Load a hierarchy mapping from a YAML/JSON file or dict.

    Args:
        source: Path to YAML/JSON file, or a dict with hierarchy definition.

    Returns:
        Parsed HierarchyMap.
    """
    if isinstance(source, dict):
        data = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Hierarchy map file not found: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Hierarchy map must be a dict/object at top level")

    mapping: dict[str, HierarchyEntry] = {}
    for label, entry in data.get("mapping", {}).items():
        mapping[str(label).strip()] = HierarchyEntry(
            level1=str(entry["level1"]).strip(),
            level2=str(entry["level2"]).strip(),
            level3=str(entry["level3"]).strip(),
        )

    return HierarchyMap(
        name=data.get("name", "unnamed"),
        mapping=mapping,
    )


# ---------------------------------------------------------------------------
# Gating logic
# ---------------------------------------------------------------------------


def _evaluate_rule(
    rule: GatingRule,
    expression: dict[str, float],
) -> bool:
    """Check if a gating rule fires for the given marker expression values.

    A rule fires when ALL markers in the rule exceed their threshold.
    """
    for marker, threshold in rule.markers.items():
        value = expression.get(marker)
        if value is None or value <= threshold:
            return False
    return True


def classify_cell(
    expression: dict[str, float],
    panel: MarkerPanel,
) -> tuple[str, str]:
    """Classify a single cell using the marker panel rules.

    Rules are evaluated in priority order (highest first). The first matching
    rule determines the label.

    Args:
        expression: Marker name -> expression value for this cell.
        panel: The marker panel with gating rules.

    Returns:
        Tuple of (label, rule_id). If no rule fires, returns
        (panel.default_label, "no_match").
    """
    # Sort rules by priority descending
    sorted_rules = sorted(panel.rules, key=lambda r: r.priority, reverse=True)

    for rule in sorted_rules:
        if _evaluate_rule(rule, expression):
            return rule.label, rule.rule_id

    return panel.default_label, "no_match"


def gate(
    cell_expressions: dict[str, dict[str, float]],
    marker_panel: MarkerPanel | dict[str, Any],
    hierarchy_map: HierarchyMap | dict[str, Any] | None = None,
    hierarchy_level: Literal["L1", "L2", "L3"] = "L3",
) -> GatingResult:
    """Classify cells using marker expression thresholds from a marker panel.

    Args:
        cell_expressions: cell_id -> {marker_name: expression_value}
        marker_panel: MarkerPanel instance or dict to load from.
        hierarchy_map: Optional HierarchyMap for label remapping.
        hierarchy_level: Which hierarchy level to output labels at.

    Returns:
        GatingResult with per-cell labels, rule IDs, and provenance.
    """
    # Resolve panel
    if isinstance(marker_panel, dict):
        panel = load_marker_panel(marker_panel)
    else:
        panel = marker_panel

    # Resolve hierarchy
    h_map: HierarchyMap | None = None
    if hierarchy_map is not None:
        if isinstance(hierarchy_map, dict):
            h_map = load_hierarchy_map(hierarchy_map)
        else:
            h_map = hierarchy_map

    cell_labels: dict[str, str] = {}
    gating_rule_ids: dict[str, str] = {}

    for cell_id, expression in cell_expressions.items():
        label, rule_id = classify_cell(expression, panel)

        # Apply hierarchy mapping if provided
        if h_map is not None:
            label = map_label_to_level(label, h_map, hierarchy_level)

        cell_labels[cell_id] = label
        gating_rule_ids[cell_id] = rule_id

    return GatingResult(
        cell_labels=cell_labels,
        gating_rule_ids=gating_rule_ids,
        marker_panel_version=panel.version,
        hierarchy_level=hierarchy_level,
    )


# ---------------------------------------------------------------------------
# Hierarchy mapping
# ---------------------------------------------------------------------------


def map_label_to_level(
    label: str,
    hierarchy_map: HierarchyMap,
    level: Literal["L1", "L2", "L3"] = "L3",
) -> str:
    """Map a label to the specified hierarchy level.

    Args:
        label: The raw gating label.
        hierarchy_map: The hierarchy mapping definition.
        level: Target hierarchy level.

    Returns:
        The mapped label at the requested level, or the original label
        if not found in the hierarchy.
    """
    entry = hierarchy_map.mapping.get(label)
    if entry is None:
        # Try case-insensitive lookup
        label_lower = label.lower()
        for key, val in hierarchy_map.mapping.items():
            if key.lower() == label_lower:
                entry = val
                break

    if entry is None:
        return label

    level_map = {"L1": entry.level1, "L2": entry.level2, "L3": entry.level3}
    return level_map[level]


def validate_hierarchy_consistency(
    labels: dict[str, str],
    hierarchy_map: HierarchyMap,
    level: Literal["L1", "L2", "L3"] = "L3",
) -> list[str]:
    """Validate that all labels are valid entries in the hierarchy at the given level.

    Returns a list of invalid labels (empty if all valid).
    """
    valid_labels_at_level: set[str] = set()
    for entry in hierarchy_map.mapping.values():
        level_map = {"L1": entry.level1, "L2": entry.level2, "L3": entry.level3}
        valid_labels_at_level.add(level_map[level])

    invalid: list[str] = []
    for cell_id, label in labels.items():
        if label not in valid_labels_at_level:
            invalid.append(label)

    return invalid


def validate_parent_child_consistency(
    hierarchy_map: HierarchyMap,
) -> list[str]:
    """Validate that child labels are consistent with parent labels in the hierarchy.

    For every entry, L3 must be a child of L2, and L2 must be a child of L1.
    This means: for any two entries sharing the same L3, they must share the same L2;
    for any two entries sharing the same L2, they must share the same L1.

    Returns a list of inconsistency descriptions (empty if consistent).
    """
    # Check L3 -> L2 consistency: same L3 must always map to same L2
    l3_to_l2: dict[str, str] = {}
    l2_to_l1: dict[str, str] = {}
    issues: list[str] = []

    for label, entry in hierarchy_map.mapping.items():
        if entry.level3 in l3_to_l2:
            if l3_to_l2[entry.level3] != entry.level2:
                issues.append(
                    f"L3 '{entry.level3}' maps to both L2 '{l3_to_l2[entry.level3]}' "
                    f"and L2 '{entry.level2}'"
                )
        else:
            l3_to_l2[entry.level3] = entry.level2

        if entry.level2 in l2_to_l1:
            if l2_to_l1[entry.level2] != entry.level1:
                issues.append(
                    f"L2 '{entry.level2}' maps to both L1 '{l2_to_l1[entry.level2]}' "
                    f"and L1 '{entry.level1}'"
                )
        else:
            l2_to_l1[entry.level2] = entry.level1

    return issues


# ---------------------------------------------------------------------------
# Pre-built hierarchy map constructors
# ---------------------------------------------------------------------------


def build_general_hierarchy_map(
    mapping_data: dict[str, dict[str, str]],
) -> HierarchyMap:
    """Build a general L1/L2/L3 hierarchy map from a mapping dict.

    Args:
        mapping_data: label -> {"level1": ..., "level2": ..., "level3": ...}
    """
    entries = {}
    for label, levels in mapping_data.items():
        entries[label] = HierarchyEntry(
            level1=levels["level1"],
            level2=levels["level2"],
            level3=levels["level3"],
        )
    return HierarchyMap(name="general", mapping=entries)


def build_myeloid_hierarchy_map(
    mapping_data: dict[str, dict[str, str]],
) -> HierarchyMap:
    """Build a myeloid-specific hierarchy map."""
    entries = {}
    for label, levels in mapping_data.items():
        entries[label] = HierarchyEntry(
            level1=levels["level1"],
            level2=levels["level2"],
            level3=levels["level3"],
        )
    return HierarchyMap(name="myeloid", mapping=entries)


def build_stromal_hierarchy_map(
    mapping_data: dict[str, dict[str, str]],
    version: Literal["v1", "v2"] = "v1",
) -> HierarchyMap:
    """Build a stromal-specific hierarchy map (v1 or v2)."""
    entries = {}
    for label, levels in mapping_data.items():
        entries[label] = HierarchyEntry(
            level1=levels["level1"],
            level2=levels["level2"],
            level3=levels["level3"],
        )
    return HierarchyMap(name=f"stromal_{version}", mapping=entries)
