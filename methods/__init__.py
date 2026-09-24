"""Zerna Scientific Methods - Isolated single-cell analysis methods."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "MethodDefinition",
    "DoubletDetectionMethod",
    "HVGSelectionMethod",
    "NormalizationMethod",
    "QCFilterMethod",
]


def __getattr__(name: str):
    if name == "MethodDefinition":
        from methods.base import MethodDefinition

        return MethodDefinition
    if name == "DoubletDetectionMethod":
        from methods.preprocessing.doublet_detection import DoubletDetectionMethod

        return DoubletDetectionMethod
    if name == "HVGSelectionMethod":
        from methods.preprocessing.hvg_selection import HVGSelectionMethod

        return HVGSelectionMethod
    if name == "NormalizationMethod":
        from methods.preprocessing.normalization import NormalizationMethod

        return NormalizationMethod
    if name == "QCFilterMethod":
        from methods.preprocessing.qc_filter import QCFilterMethod

        return QCFilterMethod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
