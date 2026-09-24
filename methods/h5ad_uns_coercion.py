"""Shared coercion of Python objects for AnnData ``uns`` prior to ``write_h5ad``.

Kept dependency-light (numpy + optional pandas only) so annotation and QC code can share
it without importing ``zerna_contracts`` or heavy pipeline modules.
"""

from __future__ import annotations

import logging
import math
import numbers
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _sanitize_for_h5ad_uns(value: Any, *, _path: str = "") -> Any:
    """Recursively coerce values so AnnData.write_h5ad can store ``uns`` (no numpy/pandas objects).

    h5py variable-length string datasets reject numpy scalar types and object arrays mixed
    with strings. JSON-serializable primitives (after ``allow_nan=False``) are a practical
    stand-in for h5ad-safe content.
    """
    if value is None:
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, np.floating):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.dtype == object:
            flat = value.ravel().tolist()
            return [_sanitize_for_h5ad_uns(x, _path=f"{_path}[]") for x in flat]
        return _sanitize_for_h5ad_uns(value.tolist(), _path=_path)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_h5ad_uns(v, _path=f"{_path}[]") for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            sk = str(k)
            child = f"{_path}.{sk}" if _path else sk
            out[sk] = _sanitize_for_h5ad_uns(v, _path=child)
        return out
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            records = value.replace({np.nan: None}).to_dict(orient="records")
            return _sanitize_for_h5ad_uns(records, _path=_path)
        if isinstance(value, (pd.Series, pd.Index)):
            return _sanitize_for_h5ad_uns(value.tolist(), _path=_path)
    except ImportError:
        pass
    logger.warning(
        "h5ad_uns: coerced non-h5ad-safe type %s at %s to str via repr",
        type(value).__name__,
        _path or "<root>",
    )
    return repr(value)
