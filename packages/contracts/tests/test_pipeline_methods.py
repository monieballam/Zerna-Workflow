"""Pipeline method registry alignment with worker and API validation."""

from zerna_contracts.pipeline_methods import METHOD_ALIASES, METHOD_REGISTRY


def test_ambient_correction_registered_for_runtime_resolution():
    assert "ambient_correction" in METHOD_REGISTRY
    module_path, class_name = METHOD_REGISTRY["ambient_correction"]
    assert module_path == "methods.preprocessing.ambient_correction"
    assert class_name == "AmbientCorrectionMethod"


def test_batch_alias_maps_to_catalog_step_name():
    assert METHOD_ALIASES.get("batch_correction") == "batch_correct"
