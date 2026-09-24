"""Tests for read-time merging of template dependency edges from the catalog."""

from apps.api.services.pipeline_catalog import (
    build_pipeline_dependencies,
    normalize_pipeline_template_definition,
)


def test_normalize_adds_missing_normalize_to_ambient_edge():
    methods = [
        "qc_filter",
        "doublet_detection",
        {"name": "ambient_correction", "enabled_if": "ambient_correction"},
        "normalize",
        "select_hvg",
    ]
    stale = {
        "methods": methods,
        "dependencies": {
            "doublet_detection": ["qc_filter"],
            "normalize": ["doublet_detection"],
            "select_hvg": ["normalize"],
        },
        "parameter_schema": {"properties": {}},
    }
    out = normalize_pipeline_template_definition(stale)
    canonical = build_pipeline_dependencies(methods)
    assert "ambient_correction" in canonical["normalize"]
    assert "ambient_correction" in out["dependencies"]["normalize"]
    assert out["metadata"].get("dependency_edges_merged_from_catalog") is True


def test_normalize_idempotent_when_already_canonical():
    methods = [
        "qc_filter",
        "doublet_detection",
        {"name": "ambient_correction", "enabled_if": "ambient_correction"},
        "normalize",
    ]
    canonical_deps = build_pipeline_dependencies(methods)
    definition = {
        "methods": methods,
        "dependencies": dict(canonical_deps),
        "parameter_schema": {"properties": {}},
    }
    out = normalize_pipeline_template_definition(definition)
    assert "dependency_edges_merged_from_catalog" not in (out.get("metadata") or {})
