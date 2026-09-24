"""Activities for run execution workflow."""

import asyncio
import json
import logging
import os
import shutil
import sys

# Before Scanpy/Numba (neighbors, Leiden, UMAP): avoid broken TBB backend in containers.
_numba_tl_boot = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
if _numba_tl_boot in ("", "tbb"):
    os.environ["NUMBA_THREADING_LAYER"] = "workqueue"
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from copy import deepcopy
from datetime import datetime
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import anndata as ad
from zerna_contracts.dataset_files import METADATA_FILENAMES
from zerna_contracts.enums import ArtifactType, ComputeBackend, ComputePreference, RunStatus
from zerna_contracts.pipeline_methods import METHOD_ALIASES, METHOD_REGISTRY
from zerna_contracts.run_checkpoint import RunCheckpoint
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from temporalio import activity

from apps.api.dependencies import _get_session_factory as _get_sf
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run
from apps.api.services.pipeline_catalog import normalize_pipeline_template_definition
from apps.api.services.pipeline_service import PipelineService
from apps.api.services.s3_service import raise_s3_upload_error_with_storage_hint
from methods.annotation.uns_h5ad_serialization import (
    sanitize_explorer_uns_for_h5ad as _sanitize_explorer_uns_for_h5ad,
)
from methods.pipeline.integration_provenance import (
    finalize_zerna_integration_provenance,
    resolve_integration_engine,
)

logger = logging.getLogger(__name__)

# Log prefix for end-of-run finalization (embedding export, secondary artifacts, summaries).
FINALIZE_LOG = "[finalize]"

# Steps run in the worker process only when we need asyncio heartbeats around long in-proc work.
# doublet_detection stays out: Scrublet/numba/BLAS can abort the interpreter on some hosts
# (e.g. macOS + Py 3.13) during "Calculating doublet scores...". Subprocess isolation keeps the
# Temporal worker alive and surfaces a step error instead of killing the whole worker.
IN_PROCESS_STEPS = {
    "run_pca",
    "cluster",
    "embed",
    "annotate",
}

# The first raw-data QC pass is memory-sensitive on larger 10x bundles. Running it in the
# existing worker process avoids paying an extra Python-process overhead before the first
# filtered snapshot exists.
RAW_FIRST_STEP_IN_PROCESS_STEPS = {
    "qc_filter",
}

STEP_LABELS = {
    "qc_filter": "QC & Filtering",
    "ambient_correction": "Ambient RNA correction",
    "doublet_detection": "Doublet Detection",
    "normalize": "Normalization",
    "select_hvg": "HVG Selection",
    "run_pca": "PCA",
    "batch_correction_harmony": "Batch Correction (Harmony)",
    "batch_correction_scvi": "Batch Correction (scVI)",
    "cluster": "Clustering",
    "embed": "Embedding",
    "annotate": "Annotation",
    "differential_expression": "Differential Expression",
    "pathway_scoring": "Pathway Activity Scoring",
    "ligand_receptor_analysis": "Ligand-Receptor Analysis",
}

LIVENESS_LOG_INTERVAL_SECONDS = 30.0
KNOWLEDGE_PACK_DIR = Path(__file__).resolve().parents[2] / "scripts" / "data" / "knowledge_packs"
BUILTIN_PATHWAY_PACKS = {
    "progeny": KNOWLEDGE_PACK_DIR / "progeny_v1.json",
    "hallmark": KNOWLEDGE_PACK_DIR / "msigdb_hallmark_v1.json",
    "kegg": KNOWLEDGE_PACK_DIR / "kegg_pathways_v1.json",
    "reactome": KNOWLEDGE_PACK_DIR / "reactome_pathways_v1.json",
    "go_biological_process": KNOWLEDGE_PACK_DIR / "go_biological_process_v1.json",
}
LEGACY_ZERNA_PATHWAY_PACKS: dict[str, Path] = {}


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Read a positive float from the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using %.2f", name, raw, default)
        return default
    if value <= 0:
        logger.warning("Non-positive float for %s=%r; using %.2f", name, raw, default)
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean-like environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid boolean for %s=%r; using %s", name, raw, default)
    return default


def _format_bytes(num_bytes: int) -> str:
    """Format a byte count for logs and user-facing errors."""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(max(0, num_bytes))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


H5AD_MEMORY_GUARD_ENABLED = _env_bool("ZERNA_ENABLE_H5AD_MEMORY_GUARD", True)
H5AD_MEMORY_GUARD_HEADROOM_BYTES = (
    _env_int("ZERNA_H5AD_MEMORY_GUARD_HEADROOM_GB", 4) * 1024 * 1024 * 1024
)
H5AD_MEMORY_GUARD_MULTIPLIER = _env_float("ZERNA_H5AD_MEMORY_GUARD_MULTIPLIER", 2.0)


def _available_memory_bytes() -> int | None:
    """Return currently available system memory when it can be determined."""
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception as exc:
        logger.warning("Could not determine available system memory: %s", exc)
        return None


def _estimate_h5ad_node_storage_bytes(node: Any) -> int:
    """Estimate on-disk bytes for one H5AD matrix-like node."""
    try:
        import h5py
    except Exception:
        return 0

    if isinstance(node, h5py.Dataset):
        return int(node.size) * int(node.dtype.itemsize)
    if isinstance(node, h5py.Group):
        if all(key in node for key in ("data", "indices", "indptr")):
            return sum(
                _estimate_h5ad_node_storage_bytes(node[key])
                for key in ("data", "indices", "indptr")
            )
        if "X" in node:
            return _estimate_h5ad_node_storage_bytes(node["X"])
    return 0


def _estimate_h5ad_in_memory_requirement_bytes(path: str | Path) -> int:
    """Estimate a safe memory budget for loading one H5AD eagerly."""
    import h5py

    file_path = Path(path)
    file_size_bytes = file_path.stat().st_size
    estimated_payload_bytes = 0

    with h5py.File(file_path, "r") as handle:
        if "X" in handle:
            estimated_payload_bytes += _estimate_h5ad_node_storage_bytes(handle["X"])
        if "raw" in handle and isinstance(handle["raw"], h5py.Group) and "X" in handle["raw"]:
            estimated_payload_bytes += _estimate_h5ad_node_storage_bytes(handle["raw"]["X"])
        if "layers" in handle and isinstance(handle["layers"], h5py.Group):
            estimated_payload_bytes += sum(
                _estimate_h5ad_node_storage_bytes(layer) for layer in handle["layers"].values()
            )

    return int(max(file_size_bytes, estimated_payload_bytes) * H5AD_MEMORY_GUARD_MULTIPLIER)


def _guard_h5ad_memory_budget(paths: list[str | Path]) -> None:
    """Fail fast when an H5AD eager-load would exceed the worker's safe memory budget."""
    if not H5AD_MEMORY_GUARD_ENABLED or not paths:
        return

    available_bytes = _available_memory_bytes()
    if available_bytes is None:
        return

    safe_budget_bytes = max(0, available_bytes - H5AD_MEMORY_GUARD_HEADROOM_BYTES)
    if safe_budget_bytes <= 0:
        raise ValueError(
            "This worker does not have enough free memory to load H5AD inputs safely. "
            f"Available={_format_bytes(available_bytes)}, "
            f"required headroom={_format_bytes(H5AD_MEMORY_GUARD_HEADROOM_BYTES)}."
        )

    estimated_required_bytes = 0
    for path in paths:
        estimated_required_bytes += _estimate_h5ad_in_memory_requirement_bytes(path)

    logger.info(
        "H5AD memory guard estimated %s required across %d file(s); safe budget is %s.",
        _format_bytes(estimated_required_bytes),
        len(paths),
        _format_bytes(safe_budget_bytes),
    )

    if estimated_required_bytes > safe_budget_bytes:
        raise ValueError(
            "Dataset is too large for safe in-memory H5AD loading on this worker. "
            f"Estimated requirement={_format_bytes(estimated_required_bytes)}, "
            f"safe budget={_format_bytes(safe_budget_bytes)}, "
            f"available now={_format_bytes(available_bytes)}. "
            "Use a larger worker, import a sharded 10x/MTX input, or explicitly disable "
            "the guard with ZERNA_ENABLE_H5AD_MEMORY_GUARD=0 if you have validated the host."
        )


def _normalize_species_symbol(symbol: str, species: str) -> str:
    """Coerce pathway/resource symbols to the dataset's expected species casing."""
    from methods.annotation.ligand_receptor import _human_symbol_to_mouse_symbol

    cleaned = str(symbol).strip()
    if not cleaned:
        return cleaned
    if str(species).strip().lower() == "mouse":
        return _human_symbol_to_mouse_symbol(cleaned)
    return cleaned.upper()


def _knowledge_pack_to_network(pack_path: Path, *, species: str) -> Any:
    """Convert bundled knowledge-pack JSON into a decoupler-compatible network."""
    import pandas as pd

    if not pack_path.is_file():
        raise FileNotFoundError(f"Bundled knowledge pack not found: {pack_path}")

    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    pathways = payload.get("pathways")
    if not isinstance(pathways, dict):
        raise ValueError(f"Knowledge pack {pack_path} is missing a 'pathways' mapping")

    rows: list[dict[str, Any]] = []
    for pathway_name, genes in pathways.items():
        if isinstance(genes, dict):
            iterable = genes.items()
        elif isinstance(genes, list):
            iterable = ((gene, 1.0) for gene in genes)
        else:
            continue
        for gene, weight in iterable:
            rows.append(
                {
                    "source": str(pathway_name),
                    "target": _normalize_species_symbol(str(gene), species),
                    "weight": float(weight) if weight is not None else 1.0,
                }
            )

    return pd.DataFrame(rows, columns=["source", "target", "weight"])


def _legacy_zerna_pathway_pack_to_network(pack_path: Path, *, species: str) -> Any:
    """Convert old Zerna pathway JSON maps into a decoupler-compatible network."""
    import pandas as pd

    if not pack_path.is_file():
        raise FileNotFoundError(f"Legacy Zerna pathway pack not found: {pack_path}")

    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Legacy Zerna pathway pack {pack_path} is not a pathway mapping")

    rows: list[dict[str, Any]] = []
    for pathway_name, genes in payload.items():
        if not isinstance(genes, list):
            continue
        for gene in genes:
            cleaned_gene = _normalize_species_symbol(str(gene), species)
            if not cleaned_gene:
                continue
            rows.append(
                {
                    "source": str(pathway_name),
                    "target": cleaned_gene,
                    "weight": 1.0,
                }
            )
    return pd.DataFrame(rows, columns=["source", "target", "weight"])


def _load_builtin_pathway_network(
    pathway_database: str,
    *,
    species: str,
    progeny_top: int = 500,
):
    """Resolve built-in pathway resources without requiring local file paths."""
    normalized_database = str(pathway_database or "PROGENy").strip().lower()
    if normalized_database == "progeny":
        import decoupler as dc

        try:
            return dc.op.progeny(
                organism=species,
                top=max(1, int(progeny_top)),
                verbose=False,
            )
        except Exception as exc:
            logger.warning(
                "Falling back to bundled PROGENy knowledge pack after decoupler loader failed: %s",
                exc,
            )
            return _knowledge_pack_to_network(
                BUILTIN_PATHWAY_PACKS["progeny"],
                species=species,
            )
    if normalized_database == "dorothea":
        import decoupler as dc

        return dc.op.dorothea(
            organism=species,
            verbose=False,
        )
    if normalized_database in LEGACY_ZERNA_PATHWAY_PACKS:
        return _legacy_zerna_pathway_pack_to_network(
            LEGACY_ZERNA_PATHWAY_PACKS[normalized_database],
            species=species,
        )
    if normalized_database in BUILTIN_PATHWAY_PACKS:
        return _knowledge_pack_to_network(
            BUILTIN_PATHWAY_PACKS[normalized_database],
            species=species,
        )
    raise ValueError(
        "Unsupported built-in pathway database "
        f"'{pathway_database}'. Expected PROGENy, DoRothEA, Hallmark, KEGG, Reactome, "
        "GO_Biological_Process, or Custom."
    )


def _normalize_runtime_parameters(adata, parameters: dict[str, Any]) -> dict[str, Any]:
    """Normalize dataset-aware parameter keys against the current AnnData object."""
    from methods.data.obs_keys import resolve_batch_key, resolve_cluster_key

    def _match_obs_column(requested: Any) -> str | None:
        requested_clean = str(requested or "").strip()
        if not requested_clean:
            return None
        obs_lookup = {str(column).lower(): str(column) for column in adata.obs.columns}
        return obs_lookup.get(requested_clean.lower())

    def _preferred_cluster_key() -> str:
        clustering_method = str(normalized.get("clustering_method") or "leiden").strip().lower()
        return "louvain" if clustering_method == "louvain" else "leiden"

    normalized = dict(parameters)
    batch_key = resolve_batch_key(adata, normalized.get("batch_key"), strict=False)
    if batch_key:
        normalized["batch_key"] = batch_key
    else:
        normalized.pop("batch_key", None)

    hvg_batch_key = resolve_batch_key(adata, normalized.get("hvg_batch_key"), strict=False)
    if hvg_batch_key:
        normalized["hvg_batch_key"] = hvg_batch_key
    elif batch_key and not normalized.get("hvg_batch_key"):
        normalized["hvg_batch_key"] = batch_key
    else:
        normalized.pop("hvg_batch_key", None)

    preferred_cluster_key = _preferred_cluster_key()
    requested_cluster_key = str(normalized.get("cluster_key") or "").strip()
    if requested_cluster_key.lower() in {"cluster", "leiden", "louvain"}:
        normalized["cluster_key"] = (
            _match_obs_column(requested_cluster_key) or requested_cluster_key.lower()
        )
    elif requested_cluster_key:
        resolved_cluster_key = resolve_cluster_key(adata, requested_cluster_key, strict=False)
        if resolved_cluster_key:
            normalized["cluster_key"] = resolved_cluster_key
        else:
            normalized["cluster_key"] = (
                _match_obs_column(preferred_cluster_key) or preferred_cluster_key
            )
    else:
        normalized["cluster_key"] = (
            _match_obs_column(preferred_cluster_key) or preferred_cluster_key
        )

    requested_annotation_cluster_key = str(normalized.get("annotation_cluster_key") or "").strip()
    if requested_annotation_cluster_key:
        if requested_annotation_cluster_key.lower() in {"cluster", "leiden", "louvain"}:
            normalized["annotation_cluster_key"] = (
                _match_obs_column(requested_annotation_cluster_key)
                or requested_annotation_cluster_key.lower()
            )
        else:
            annotation_cluster_key = resolve_cluster_key(
                adata,
                requested_annotation_cluster_key,
                strict=False,
            )
            if annotation_cluster_key:
                normalized["annotation_cluster_key"] = annotation_cluster_key
            else:
                normalized.pop("annotation_cluster_key", None)

    raw_lr_cg = normalized.get("lr_communication_grouping")
    if raw_lr_cg is not None and str(raw_lr_cg).strip():
        v = str(raw_lr_cg).strip().lower()
        allowed = frozenset({"auto", "cci_major", "cci_minor", "cci_fine", "cluster"})
        normalized["lr_communication_grouping"] = v if v in allowed else "auto"

    return normalized


def _release_process_memory(reason: str) -> None:
    """Aggressively reclaim Python/native heap pages between large pipeline phases."""
    import gc

    gc.collect()

    try:
        import torch

        if hasattr(torch, "cuda") and callable(getattr(torch.cuda, "empty_cache", None)):
            torch.cuda.empty_cache()
        if hasattr(torch, "mps") and callable(getattr(torch.mps, "empty_cache", None)):
            torch.mps.empty_cache()
    except Exception:
        pass

    if sys.platform.startswith("linux"):
        try:
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

    logger.info("Released process memory after %s", reason)


PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_env_int(
        "ZERNA_PIPELINE_STEP_WORKERS",
        min(8, max(4, os.cpu_count() or 4)),
    )
)
PIPELINE_ACTIVITY_LIMIT = _env_int("ZERNA_MAX_CONCURRENT_PIPELINES", 1)
PIPELINE_ACTIVITY_SEMAPHORE = asyncio.Semaphore(PIPELINE_ACTIVITY_LIMIT)
GPU_STEP_SEMAPHORE = threading.BoundedSemaphore(_env_int("ZERNA_MAX_CONCURRENT_GPU_STEPS", 1))
EXECUTION_STATE_PARAMETER_KEY = "_execution_state"
CHECKPOINTS_PARAMETER_KEY = "_checkpoints"


async def _run_blocking(func, /, *args, **kwargs):
    """Run blocking scientific code on a shared worker pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(PIPELINE_EXECUTOR, partial(func, *args, **kwargs))


async def _safe_touch_run_progress(
    run_id: str,
    *,
    state: str | None = None,
    current_step: str | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Refresh run progress without letting liveness bookkeeping stall the activity."""
    try:
        await asyncio.wait_for(
            _touch_run_progress(
                run_id=run_id,
                state=state,
                current_step=current_step,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        logger.warning(
            "Timed out while refreshing run progress timestamp for %s during step %s",
            run_id,
            current_step,
        )
    except Exception as exc:
        logger.warning(
            "Failed to refresh run progress timestamp for %s during step %s: %s",
            run_id,
            current_step,
            exc,
        )


async def _run_blocking_with_heartbeats(
    func,
    /,
    *args,
    heartbeat_details: dict[str, Any] | None = None,
    interval_seconds: float = 15.0,
    **kwargs,
):
    """Run blocking work while heartbeating from the activity task itself."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(PIPELINE_EXECUTOR, partial(func, *args, **kwargs))
    last_progress_touch = monotonic()

    while True:
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=interval_seconds)
        except TimeoutError:
            if heartbeat_details is None:
                continue
            activity.heartbeat(heartbeat_details)
            run_id = heartbeat_details.get("run_id")
            now = monotonic()
            if isinstance(run_id, str) and now - last_progress_touch >= 30.0:
                await _safe_touch_run_progress(
                    run_id=run_id,
                    state="running",
                    current_step=heartbeat_details.get("current_step"),
                )
                last_progress_touch = now


async def _heartbeat_while_running(details: dict[str, Any], interval_seconds: float = 15.0) -> None:
    """Emit periodic activity heartbeats while a blocking step is running."""
    last_progress_touch = 0.0
    last_liveness_log = 0.0
    while True:
        try:
            activity.heartbeat(details)
            run_id = details.get("run_id")
            now = monotonic()
            if isinstance(run_id, str) and now - last_progress_touch >= 30.0:
                await _safe_touch_run_progress(
                    run_id=run_id,
                    state="running",
                    current_step=details.get("current_step"),
                )
                last_progress_touch = now
            if now - last_liveness_log >= LIVENESS_LOG_INTERVAL_SECONDS:
                completed_steps = details.get("completed_steps")
                total_steps = details.get("total_steps")
                current_step = details.get("current_step")
                elapsed_seconds = int(now - float(details.get("activity_started_monotonic", now)))
                if (
                    isinstance(completed_steps, list)
                    and isinstance(total_steps, int)
                    and total_steps > 0
                ):
                    progress = f"{len(completed_steps)}/{total_steps}"
                else:
                    progress = "n/a"
                logger.info(
                    "Run %s still active. phase=%s step=%s progress=%s elapsed=%ss",
                    run_id,
                    details.get("phase"),
                    current_step or "-",
                    progress,
                    elapsed_seconds,
                )
                last_liveness_log = now
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Background heartbeat loop hit an error for run %s during step %s: %s",
                details.get("run_id"),
                details.get("current_step"),
                exc,
            )
        await asyncio.sleep(interval_seconds)


async def _acquire_pipeline_slot(
    run_id: str,
    heartbeat_details: dict[str, Any],
    *,
    interval_seconds: float = 15.0,
) -> None:
    """Serialize memory-heavy pipeline executions to avoid worker OOMs."""
    wait_started = monotonic()
    heartbeat_details["phase"] = "waiting_for_worker_capacity"

    while True:
        try:
            await asyncio.wait_for(
                PIPELINE_ACTIVITY_SEMAPHORE.acquire(),
                timeout=interval_seconds,
            )
            waited_seconds = int(monotonic() - wait_started)
            logger.info(
                "Run %s acquired pipeline slot after %ss (max_concurrent_pipelines=%d)",
                run_id,
                waited_seconds,
                PIPELINE_ACTIVITY_LIMIT,
            )
            heartbeat_details["phase"] = "initializing"
            return
        except TimeoutError:
            logger.info(
                "Run %s waiting for pipeline slot for %ss (max_concurrent_pipelines=%d)",
                run_id,
                int(monotonic() - wait_started),
                PIPELINE_ACTIVITY_LIMIT,
            )


async def _capture_subprocess_stream(
    stream: asyncio.StreamReader,
    *,
    sink_path: Path,
    run_id: str | UUID,
    step_name: str,
    stream_name: str,
) -> str:
    """Stream child-process output to disk and the worker logs in real time."""
    lines: list[str] = []
    log = logger.warning if stream_name == "stderr" else logger.info

    with sink_path.open("w", encoding="utf-8") as sink:
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace").rstrip()
            sink.write(text)
            sink.write("\n")
            sink.flush()
            if text:
                log("Run %s step %s %s: %s", run_id, step_name, stream_name, text)
                lines.append(text)

    return "\n".join(lines).strip()


def _is_gpu_backend(backend: ComputeBackend | None) -> bool:
    """Return whether the selected backend is a real GPU backend."""
    return backend not in (None, ComputeBackend.CPU)


def _compute_backend_label(compute) -> str:
    """Return a stable backend label for metrics and logs."""
    backend = getattr(compute, "selected_backend", None)
    if isinstance(backend, ComputeBackend):
        return backend.value
    return "cpu"


def _build_compute_context(method) -> Any | None:
    """Create a compute context aligned with the method preference."""
    try:
        from zerna_gpu_abstraction.compute_context import ComputeContext
    except Exception as exc:
        logger.warning("GPU abstraction unavailable; running on CPU: %s", exc)
        return None

    preference = getattr(method, "compute_preference", ComputePreference.CPU_ONLY)
    compute = ComputeContext()

    try:
        compute.detect_hardware()
        compute.select_backend(preference)
    except Exception as exc:
        if preference == ComputePreference.GPU_REQUIRED:
            raise
        logger.warning(
            "Falling back to CPU backend for %s: %s",
            getattr(method, "name", type(method).__name__),
            exc,
        )
        compute.selected_backend = ComputeBackend.CPU

    supported_backends = getattr(method, "supported_backends", None)
    if supported_backends is not None:
        normalized_backends = set(supported_backends)
        normalized_backends.add(ComputeBackend.CPU)
        if compute.selected_backend not in normalized_backends:
            logger.info(
                "Backend %s is unsupported for %s; falling back to CPU.",
                _compute_backend_label(compute),
                getattr(method, "name", type(method).__name__),
            )
            compute.selected_backend = ComputeBackend.CPU

    return compute


@contextmanager
def _reserve_compute_slot(compute):
    """Serialize GPU-heavy steps while still allowing concurrent CPU work."""
    backend = getattr(compute, "selected_backend", None)
    if not _is_gpu_backend(backend):
        yield
        return

    logger.info("Waiting for GPU slot on backend %s", _compute_backend_label(compute))
    GPU_STEP_SEMAPHORE.acquire()
    try:
        yield
    finally:
        GPU_STEP_SEMAPHORE.release()


def _get_method_instance(method_name: str):
    """Dynamically import and instantiate a method class."""
    if method_name not in METHOD_REGISTRY:
        raise ValueError(f"Unknown method: {method_name}")
    module_path, class_name = METHOD_REGISTRY[method_name]
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


def _merge_step_parameters(step_entry: object, run_parameters: dict[str, Any]) -> dict[str, Any]:
    """Merge template-defined step params with run-time parameters."""
    merged = {}
    if isinstance(step_entry, dict):
        step_params = step_entry.get("params")
        if isinstance(step_params, dict):
            merged.update(step_params)
    merged.update(run_parameters)
    return merged


def _is_step_enabled(step_entry: object, parameters: dict[str, Any]) -> bool:
    """Return whether an optional step entry should execute for this run."""
    if not isinstance(step_entry, dict):
        return True

    enabled_if = step_entry.get("enabled_if")
    if enabled_if is None:
        return True
    if isinstance(enabled_if, str):
        return bool(parameters.get(enabled_if, False))
    if isinstance(enabled_if, list):
        return all(bool(parameters.get(key, False)) for key in enabled_if)
    return bool(enabled_if)


def _module_available(module_name: str) -> bool:
    """Return whether an optional runtime dependency can be imported."""
    import importlib
    import importlib.util

    importlib.invalidate_caches()
    return importlib.util.find_spec(module_name) is not None


def _normalize_method_name(method_name: str, parameters: dict[str, Any]) -> str:
    """Translate user/template aliases into executable method names."""
    normalized = METHOD_ALIASES.get(method_name, method_name)
    if normalized in {"batch_correct", "batch_correction_scvi"}:
        im = str(parameters.get("integration_mode") or "").strip().lower()
        if im == "scvi":
            batch_method = "scvi"
        elif im == "harmony":
            batch_method = "harmony"
        elif normalized == "batch_correction_scvi":
            batch_method = "scvi"
        else:
            batch_method = (
                str(parameters.get("batch_method") or parameters.get("method") or "harmony")
                .strip()
                .lower()
            )
        if batch_method == "scvi" and not _module_available("scvi"):
            logger.warning(
                "Batch integration: scVI was requested (integration_mode=%r, batch_method=%r) but "
                "the scvi package is not available in this worker; executing Harmony instead. "
                "Provenance records method_requested=scvi, method_executed=harmony, "
                "fallback_applied=true.",
                parameters.get("integration_mode"),
                parameters.get("batch_method"),
            )
            return "batch_correction_harmony"
        return "batch_correction_scvi" if batch_method == "scvi" else "batch_correction_harmony"
    return normalized


def _prepare_executable_steps(
    methods_list: list[Any],
    run_parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expand template methods into concrete executable steps."""
    executable_steps: list[dict[str, Any]] = []
    for step_entry in methods_list:
        raw_name = step_entry if isinstance(step_entry, str) else step_entry.get("name")
        if not raw_name:
            raise ValueError(f"Pipeline step is missing a name: {step_entry!r}")
        step_parameters = _merge_step_parameters(step_entry, run_parameters)
        if not _is_step_enabled(step_entry, step_parameters):
            continue
        executable_steps.append(
            {
                "raw_name": str(raw_name),
                "step_name": _normalize_method_name(str(raw_name), step_parameters),
                "parameters": step_parameters,
            }
        )
    return executable_steps


def _step_label(step_name: str) -> str:
    """Return a user-facing label for a pipeline step."""
    return STEP_LABELS.get(step_name, step_name.replace("_", " ").title())


def _ordered_unique_steps(step_names: list[str]) -> list[str]:
    """Return step names without duplicates while preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for step_name in step_names:
        if step_name in seen:
            continue
        seen.add(step_name)
        ordered.append(step_name)
    return ordered


def _step_needs_external_counts(step_name: str, parameters: dict[str, Any]) -> bool:
    """Return whether a step needs access to raw counts outside the current snapshot."""
    if step_name == "batch_correction_scvi":
        return True
    if step_name == "select_hvg":
        flavor = str(parameters.get("hvg_flavor", parameters.get("flavor", "seurat_v3"))).strip()
        return flavor == "seurat_v3"
    if step_name == "differential_expression":
        de_mode = str(parameters.get("de_mode") or "marker_ranking").strip().lower()
        return de_mode in {"condition_de_within_celltype", "pseudobulk_sample_level_contrast"}
    return False


def _resolve_counts_snapshot_s3_key(
    initial_snapshot_s3_key: str,
    step_outputs: dict[str, Any],
) -> str:
    """Pick the best available raw-count snapshot for downstream count-based steps."""
    for step_name in ("doublet_detection", "qc_filter"):
        snapshot_key = step_outputs.get(step_name)
        if isinstance(snapshot_key, str) and snapshot_key:
            return snapshot_key
    return initial_snapshot_s3_key


def _repair_counts_snapshot_s3_key(
    initial_snapshot_s3_key: str,
    step_outputs: dict[str, Any],
    persisted_snapshot_s3_key: str | None,
) -> str:
    """Repair stale persisted count-snapshot references for resumed runs.

    Older execution state can pin `counts_snapshot_s3_key` to the initial snapshot
    even after QC/doublet filtering completed. For count-based downstream steps like
    HVG selection or scVI, that forces the subprocess to reload a larger-than-needed
    matrix and can trigger OOM kills on resume. The durable step outputs are the
    source of truth, so always prefer the latest filtered raw-count snapshot.
    """
    resolved_snapshot_s3_key = _resolve_counts_snapshot_s3_key(
        initial_snapshot_s3_key,
        step_outputs,
    )
    if (
        persisted_snapshot_s3_key
        and persisted_snapshot_s3_key != resolved_snapshot_s3_key
        and resolved_snapshot_s3_key
    ):
        logger.info(
            "Repairing stale counts snapshot reference from %s to %s",
            persisted_snapshot_s3_key,
            resolved_snapshot_s3_key,
        )
    return resolved_snapshot_s3_key


def _format_step_summary(step_name: str, metrics: dict[str, Any]) -> str:
    """Create a brief human-readable summary for a completed pipeline step."""
    if metrics.get("skipped"):
        return str(metrics.get("reason") or "Skipped for this run.")

    if step_name == "qc_filter":
        before = metrics.get("n_cells_before")
        after = metrics.get("n_cells_after")
        genes_after = metrics.get("n_genes_after")
        if isinstance(before, int) and isinstance(after, int):
            kept = f"Retained {after:,}/{before:,} cells"
            if isinstance(genes_after, int):
                kept += f" and {genes_after:,} genes"
            return f"{kept} after QC."
        return "Applied quality-control filtering."

    if step_name == "doublet_detection":
        n_doublets = metrics.get("n_predicted_doublets")
        n_after = metrics.get("n_cells_after")
        if isinstance(n_doublets, int) and isinstance(n_after, int):
            return f"Flagged {n_doublets:,} likely doublets; {n_after:,} cells remain for analysis."
        return "Scored and filtered likely doublets."

    if step_name == "normalize":
        if metrics.get("scale_applied"):
            return "Normalized counts, computed log1p expression values, then scaled the active matrix."
        return "Normalized counts and computed log1p expression values."

    if step_name == "select_hvg":
        n_hvgs = metrics.get("n_hvgs_selected")
        n_total = metrics.get("n_genes_total")
        if isinstance(n_hvgs, int) and isinstance(n_total, int):
            return (
                f"HVG Selection: marked {n_hvgs:,} highly variable genes among {n_total:,} total "
                "genes (no immediate subsetting)."
            )
        return "HVG Selection: marked highly variable genes (no immediate subsetting)."

    if step_name == "run_pca":
        n_components = metrics.get("n_components_computed")
        used_hvg = metrics.get("use_highly_variable_effective")
        base = "Computed PCA"
        scope = (
            " on highly variable genes"
            if used_hvg is True
            else " on all genes"
            if used_hvg is False
            else ""
        )
        if isinstance(n_components, int):
            return f"{base}{scope} ({n_components} components)."
        return f"{base}{scope}."

    if step_name in {"batch_correction_harmony", "batch_correction_scvi"}:
        n_batches = metrics.get("n_batches")
        batch_key = metrics.get("batch_key")
        method_name = "scVI" if step_name == "batch_correction_scvi" else "Harmony"
        compute_backend = metrics.get("compute_backend")
        fallback_method = metrics.get("fallback_method")
        integration_fb = metrics.get("integration_fallback_applied")
        if fallback_method == "harmony" or integration_fb:
            if isinstance(batch_key, str) and batch_key:
                return (
                    "scVI was requested but unavailable in the worker runtime; "
                    f"applied Harmony on `{batch_key}` instead."
                )
            return (
                "scVI was requested but unavailable in the worker runtime; applied Harmony instead."
            )
        if isinstance(n_batches, int) and isinstance(batch_key, str) and batch_key:
            if (
                step_name == "batch_correction_scvi"
                and isinstance(compute_backend, str)
                and compute_backend
            ):
                return (
                    f"Integrated {n_batches} batches using {method_name} on `{batch_key}` "
                    f"with the `{compute_backend}` backend."
                )
            return f"Integrated {n_batches} batches using {method_name} on `{batch_key}`."
        return f"Applied {method_name} batch correction."

    if step_name == "cluster":
        n_clusters = metrics.get("n_clusters")
        method = str(metrics.get("method_executed") or metrics.get("method") or "leiden").lower()
        rep = metrics.get("representation_used") or metrics.get("use_rep")
        label = "Leiden" if method == "leiden" else "Louvain"
        if isinstance(n_clusters, int) and isinstance(rep, str) and rep:
            return f"Clustered cells with {label} using {rep} ({n_clusters} clusters)."
        if isinstance(n_clusters, int):
            return f"Clustered cells with {label} ({n_clusters} clusters)."
        return "Computed neighborhood graph and clusters."

    if step_name == "embed":
        meth = str(metrics.get("method_executed") or metrics.get("method") or "umap").lower()
        rep = metrics.get("representation_used") or metrics.get("use_rep")
        label = "t-SNE" if meth == "tsne" else "UMAP"
        if isinstance(rep, str) and rep:
            return f"Computed {label} from {rep}."
        return f"Computed {label} embedding."

    if step_name == "annotate":
        n_cells = metrics.get("n_cells_annotated")
        n_types = metrics.get("n_cell_types_predicted")
        mean_confidence = metrics.get("mean_confidence")
        meth = str(
            metrics.get("annotation_method_executed")
            or metrics.get("annotation_method_used")
            or "celltypist"
        ).lower()
        ck = metrics.get("cluster_key_resolved")
        cluster_phrase = ""
        if isinstance(ck, str) and ck.strip():
            ckl = ck.strip().lower()
            if ckl == "leiden":
                cluster_phrase = "leiden clusters"
            elif ckl == "louvain":
                cluster_phrase = "louvain clusters"
            else:
                cluster_phrase = f"`{ck.strip()}` clusters"
        if meth == "celltypist" and cluster_phrase:
            base = f"Annotated clusters using CellTypist from {cluster_phrase}"
            if isinstance(n_cells, int):
                base += f" ({n_cells:,} cells)"
            return base + "."
        parts: list[str] = []
        if isinstance(n_cells, int):
            parts.append(f"Annotated {n_cells:,} cells")
        if isinstance(n_types, int):
            parts.append(f"across {n_types} predicted cell types")
        if isinstance(mean_confidence, (int, float)):
            parts.append(f"mean confidence {mean_confidence:.2f}")
        if parts:
            return f"{', '.join(parts)}."
        return "Assigned automated cell-type labels."

    if step_name == "differential_expression":
        mode = str(metrics.get("de_mode") or "marker_ranking").strip().lower()
        if mode == "marker_ranking":
            n_clusters = metrics.get("n_clusters")
            method = metrics.get("method") or metrics.get("method_executed")
            if isinstance(n_clusters, int) and isinstance(method, str) and method:
                return f"Ranked marker genes for {n_clusters} groups using {method}."
            return "Ranked exploratory marker genes (cell-level)."
        if mode == "condition_de_within_celltype":
            n_pb = metrics.get("n_pseudobulk_profiles")
            if isinstance(n_pb, int):
                return f"Ran replicate-aware pseudobulk DE within a cell subset ({n_pb} profiles)."
            return "Ran replicate-aware pseudobulk DE within a cell subset."
        if mode == "pseudobulk_sample_level_contrast":
            n_pb = metrics.get("n_pseudobulk_profiles")
            if isinstance(n_pb, int):
                return f"Ran sample-level pseudobulk DE ({n_pb} pseudobulk profiles)."
            return "Ran sample-level pseudobulk differential expression."
        return "Completed differential expression step."

    if step_name == "pathway_scoring":
        n_pathways = metrics.get("n_pathways_scored")
        n_cells = metrics.get("n_cells")
        db = metrics.get("pathway_database")
        db_label = str(db).strip() if isinstance(db, str) and db.strip() else None
        if isinstance(n_pathways, int) and isinstance(n_cells, int) and db_label:
            return (
                f"Scored pathway activities across {n_cells:,} cells using {db_label} "
                f"({n_pathways:,} pathways)."
            )
        if db_label:
            return f"Scored pathway activities across cells using {db_label}."
        if isinstance(n_pathways, int) and isinstance(n_cells, int):
            return f"Scored pathway activities across {n_cells:,} cells ({n_pathways:,} pathways)."
        return "Scored per-cell pathway activities (decoupler-style resource scores)."

    if step_name == "ligand_receptor_analysis":
        n_interactions = metrics.get("n_interactions")
        n_pairs = metrics.get("n_cluster_pairs")
        eff = metrics.get("lr_communication_grouping_effective")
        fb = metrics.get("lr_used_cluster_fallback")
        if isinstance(n_interactions, int) and isinstance(n_pairs, int):
            if eff == "cluster" and not fb:
                base = (
                    f"Inferred ligand–receptor interactions across {n_pairs:,} directed group pairs "
                    f"using cluster labels ({n_interactions:,} interaction rows)."
                )
            elif eff in ("cci_minor", "cci_fine", "cci_major") or (
                isinstance(eff, str) and eff.startswith("cci_") and not fb
            ):
                tier = "annotation-derived cell types"
                if eff == "cci_minor":
                    tier = "annotation-derived minor cell types"
                elif eff == "cci_fine":
                    tier = "annotation-derived fine cell types"
                elif eff == "cci_major":
                    tier = "annotation-derived major cell types"
                base = (
                    f"Inferred ligand–receptor interactions using {tier} "
                    f"({n_pairs:,} directed group pairs, {n_interactions:,} interaction rows)."
                )
            else:
                base = (
                    f"Inferred ligand–receptor interactions across {n_pairs:,} directed group pairs "
                    f"({n_interactions:,} interaction rows)."
                )
            if fb:
                reason = metrics.get("lr_fallback_reason")
                tail = " Cluster grouping was used as a fallback from auto mode."
                if isinstance(reason, str) and reason.strip():
                    tail = f" Cluster fallback: {reason.strip()}"
                return base + tail
            return base
        return "Inferred ligand–receptor interactions with LIANA."

    return "Step completed successfully."


def _raise_if_step_output_empty(
    step_name: str,
    *,
    output_meta: dict[str, Any],
) -> None:
    """Stop early with a clear error when filtering removes every cell."""
    try:
        n_obs = int(output_meta.get("n_obs"))
    except (TypeError, ValueError):
        return

    if n_obs != 0:
        return

    if step_name == "qc_filter":
        raise ValueError(
            "QC filtering removed all cells. Adjust thresholds such as "
            "min_genes/max_genes/min_counts/max_counts/max_mito_pct before rerunning."
        )

    if step_name == "doublet_detection":
        raise ValueError(
            "Doublet detection left zero cells for downstream analysis. "
            "Use flag_only or relax doublet filtering before rerunning."
        )


def _build_step_progress_entry(
    step_name: str,
    status: str,
    started_at: datetime,
    completed_at: datetime,
    summary: str,
) -> dict[str, Any]:
    """Create a serializable progress entry for a finished step."""
    return {
        "step_name": step_name,
        "label": _step_label(step_name),
        "status": status,
        "summary": summary,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 1),
    }


async def _update_run_progress(
    run_id: str | UUID,
    *,
    total_steps: int | None = None,
    completed_steps: list[str] | None = None,
    current_step: str | None = None,
    current_step_started_at: datetime | None = None,
    clear_current_step: bool = False,
    progress_percent: int | None = None,
    state: str | None = None,
    step_entry: dict[str, Any] | None = None,
) -> None:
    """Persist structured pipeline progress on the run record."""
    run_uuid = UUID(str(run_id))

    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            activity.logger.warning("Unable to persist progress for missing run %s", run_uuid)
            return

        parameters = dict(run.parameters or {})
        progress = parameters.get("progress")
        if not isinstance(progress, dict):
            progress = {}

        if total_steps is not None:
            progress["total_steps"] = total_steps
        if completed_steps is not None:
            progress["completed_steps"] = _ordered_unique_steps(completed_steps)
        if progress_percent is not None:
            progress["progress_percent"] = progress_percent
        if state is not None:
            progress["state"] = state

        if current_step is not None:
            progress["current_step"] = current_step
            progress["current_step_label"] = _step_label(current_step)
            progress["current_step_started_at"] = (
                current_step_started_at.isoformat() if current_step_started_at else None
            )
        elif clear_current_step:
            progress["current_step"] = None
            progress["current_step_label"] = None
            progress["current_step_started_at"] = None

        if step_entry is not None:
            existing_entries = progress.get("step_summaries")
            if not isinstance(existing_entries, list):
                existing_entries = []
            normalized_entries = [
                item
                for item in existing_entries
                if isinstance(item, dict) and item.get("step_name") != step_entry["step_name"]
            ]
            normalized_entries.append(step_entry)
            progress["step_summaries"] = normalized_entries

        progress["updated_at"] = datetime.utcnow().isoformat()

        parameters["progress"] = progress
        run.parameters = parameters
        flag_modified(run, "parameters")
        await db.commit()


async def _touch_run_progress(
    run_id: UUID | str,
    *,
    state: str | None = None,
    current_step: str | None = None,
) -> None:
    """Refresh only the progress heartbeat timestamp for a run."""
    run_uuid = UUID(str(run_id))

    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return

        parameters = dict(run.parameters or {})
        progress = parameters.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        else:
            progress = dict(progress)

        if state is not None:
            progress["state"] = state
        if current_step is not None:
            progress["current_step"] = current_step

        progress["updated_at"] = datetime.utcnow().isoformat()
        parameters["progress"] = progress
        run.parameters = parameters
        flag_modified(run, "parameters")
        await db.commit()


def _sanitize_dataframe_for_h5ad(frame) -> None:
    """Cast mixed object/categorical columns into H5AD-safe string representations."""
    import pandas as pd

    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_categorical_dtype(series):
            converted = series.astype(object).map(
                lambda value: pd.NA if pd.isna(value) else str(value)
            )
            if pd.api.types.is_categorical_dtype(series):
                frame[column] = converted.astype("string").astype("category")
            else:
                frame[column] = converted.astype("string")


def _ensure_zerna_qc_report_h5ad_safe(adata) -> None:
    """Coerce ``zerna_qc_report['filter_rules']`` to ``filter_rules_json`` before ``write_h5ad``.

    AnnData writes Python ``list`` values under ``uns`` via a vlen UTF-8 string path when
    elements are not a single numeric dtype. Lists of dicts, numpy scalars, ints mixed
    with strings, etc. all raise ``Can't implicitly convert non-string objects to
    strings``. Storing rules as one JSON string is always h5ad-safe. Current qc_filter
    only emits ``filter_rules_json``; this migrates any legacy ``filter_rules`` list.
    """
    raw = adata.uns.get("zerna_qc_report")
    if not isinstance(raw, dict):
        return
    fr = raw.get("filter_rules")
    if not isinstance(fr, list):
        return
    rep = dict(raw)
    rep["filter_rules_json"] = json.dumps(_json_safe(fr), allow_nan=False)
    del rep["filter_rules"]
    adata.uns["zerna_qc_report"] = rep
    logger.info(
        "zerna_qc_report: migrated filter_rules list to filter_rules_json before h5ad write (%d items)",
        len(fr),
    )


def _ensure_zerna_provenance_h5ad_safe(adata) -> None:
    """Coerce legacy ``zerna_provenance['steps']`` to ``steps_json`` before ``write_h5ad``."""
    from methods.pipeline.provenance import PROVENANCE_KEY

    raw = adata.uns.get(PROVENANCE_KEY)
    if not isinstance(raw, dict):
        return
    st = raw.get("steps")
    if not isinstance(st, list):
        return
    block = dict(raw)
    block["steps_json"] = json.dumps(_json_safe(st), allow_nan=False)
    block.pop("steps", None)
    adata.uns[PROVENANCE_KEY] = block
    logger.info(
        "zerna_provenance: migrated steps list to steps_json before h5ad write (%d entries)",
        len(st),
    )


def _sanitize_adata_for_h5ad(adata) -> None:
    """Normalize AnnData payloads before writing processed H5AD artifacts."""
    _ensure_zerna_qc_report_h5ad_safe(adata)
    _ensure_zerna_provenance_h5ad_safe(adata)
    _sanitize_explorer_uns_for_h5ad(adata)
    _sanitize_dataframe_for_h5ad(adata.obs)
    _sanitize_dataframe_for_h5ad(adata.var)


def _prepare_intermediate_snapshot_adata(adata) -> None:
    """Drop reconstructable payloads before persisting step-to-step snapshots.

    Intermediate checkpoints only need the state required for downstream steps.
    Persisting both `X` and a duplicate `log1p` layer inflates snapshot size by
    multiple gigabytes on large runs and can kill subprocesses during H5AD write.
    """
    if "log1p" in getattr(adata, "layers", {}):
        del adata.layers["log1p"]
    # After normalization, downstream count-based steps reload filtered raw counts from the
    # dedicated counts snapshot. Keeping `layers['counts']` in every subsequent snapshot
    # duplicates the largest matrix on disk and is the main source of ENOSPC on large runs.
    if "zerna_normalization" in getattr(adata, "uns", {}) and "counts" in adata.layers:
        del adata.layers["counts"]


def _ensure_final_expression_layers(adata) -> None:
    """Rebuild expression layers needed in the final artifact if they were pruned."""
    if "log1p" not in getattr(adata, "layers", {}):
        adata.layers["log1p"] = adata.X.copy() if hasattr(adata.X, "copy") else adata.X


def _write_adata_snapshot(adata, output_path: str | Path) -> str:
    """Persist an AnnData snapshot atomically for step-to-step handoff."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    _sanitize_adata_for_h5ad(adata)
    with ad.settings.override(allow_write_nullable_strings=True):
        adata.write_h5ad(temp_path)
    os.replace(temp_path, output_path)
    return str(output_path)


def _read_adata_snapshot(snapshot_path: str | Path) -> ad.AnnData:
    """Load a persisted AnnData snapshot."""
    return ad.read_h5ad(snapshot_path)


def _write_json_file(path: str | Path, payload: dict[str, Any]) -> None:
    """Write JSON content atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temp_path, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    os.replace(temp_path, path)


def _read_json_file(path: str | Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    with open(path) as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _json_safe(value: object) -> object:
    """Convert nested runtime values into JSON-safe structures."""
    import numpy as np

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (datetime, UUID)):
        return str(value)
    try:
        import pandas as pd

        if isinstance(value, (pd.Series, pd.Index)):
            return _json_safe(value.tolist())
    except ImportError:
        pass
    return value


def _uns_mapping_only(value: object) -> dict[str, Any]:
    """Return a dict copy for ``uns`` payloads; never use ``x or {}`` on values that may be ndarrays."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _coerce_to_python_list(value: object, *, field: str = "") -> list[Any]:
    """Turn ``uns``/parameter values into a plain list without truth-testing ndarrays or Series."""
    import numpy as np

    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, np.ndarray):
        if field:
            logger.info(
                "%s normalized ndarray to list (size=%d) for field %r",
                FINALIZE_LOG,
                int(value.size),
                field,
            )
        return value.ravel().tolist()
    try:
        import pandas as pd

        if isinstance(value, (pd.Series, pd.Index)):
            if field:
                logger.info("%s normalized Series/Index to list for field %r", FINALIZE_LOG, field)
            return value.tolist()
    except ImportError:
        pass
    return [value]


def _coerce_str_list(value: object, *, field: str = "") -> list[str]:
    """Coerce to a list of non-empty stripped strings (column names, pathway ids, etc.)."""
    out: list[str] = []
    for item in _coerce_to_python_list(value, field=field):
        s = str(item).strip() if item is not None else ""
        if s:
            out.append(s)
    return out


def _scalar_str_for_display(value: object) -> str | None:
    """Single string for labels/metadata; safe when ``uns`` stored a numpy vector by mistake."""
    if value is None:
        return None
    import numpy as np

    if isinstance(value, np.ndarray):
        if value.size == 0:
            return None
        value = value.ravel()[0]
    try:
        import pandas as pd

        if isinstance(value, pd.Series):
            if value.empty:
                return None
            value = value.iloc[0]
    except ImportError:
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    return s


def _first_scalar_annotation_label(annotation: dict[str, Any]) -> str | None:
    """Prefer ``normalized_label`` then ``cell_type`` without ``a or b`` on ndarray values."""
    for key in ("normalized_label", "cell_type"):
        raw = annotation.get(key)
        picked = _scalar_str_for_display(raw)
        if picked:
            return picked
    return None


def _parameter_str_list(value: object, default: list[str]) -> list[str]:
    """Runtime parameter list (e.g. ribo_prefixes) — never ``param or default`` on ndarrays."""
    if value is None:
        return list(default)
    coerced = _coerce_str_list(value, field="parameter_str_list")
    return coerced if coerced else list(default)


def _create_s3_client():
    """Create the S3 client used for dataset downloads and artifact uploads."""
    import boto3

    from apps.api.config import get_settings, resolve_s3_endpoint_url

    settings = get_settings()
    s3_endpoint = resolve_s3_endpoint_url(settings)

    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def _artifacts_bucket_name() -> str:
    """Return the artifacts bucket used for durable run state and outputs."""
    from apps.api.config import get_settings

    return get_settings().s3_artifacts_bucket


def _datasets_bucket_name() -> str:
    """Return the datasets bucket used for raw input downloads."""
    from apps.api.config import get_settings

    return get_settings().s3_datasets_bucket


def _initial_snapshot_s3_key(run_id: str | UUID) -> str:
    """Return the S3 key for the initial run snapshot."""
    return f"runs/{run_id}/_state/snapshots/000_initial.h5ad"


def _step_snapshot_s3_key(run_id: str | UUID, step_name: str) -> str:
    """Return the S3 key for a completed step snapshot."""
    return f"runs/{run_id}/_state/snapshots/{step_name}.h5ad"


async def _load_execution_state(run_id: str | UUID) -> dict[str, Any]:
    """Load durable execution state from the run record."""
    run_uuid = UUID(str(run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return {}
        parameters = dict(run.parameters or {})
        execution_state = parameters.get(EXECUTION_STATE_PARAMETER_KEY)
        return execution_state if isinstance(execution_state, dict) else {}


async def _save_execution_state(run_id: str | UUID, execution_state: dict[str, Any]) -> None:
    """Persist durable execution state on the run record."""
    run_uuid = UUID(str(run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            activity.logger.warning(
                "Unable to persist execution state for missing run %s", run_uuid
            )
            return

        parameters = dict(run.parameters or {})
        parameters[EXECUTION_STATE_PARAMETER_KEY] = execution_state
        run.parameters = parameters
        flag_modified(run, "parameters")
        await db.commit()


async def _clear_execution_state(run_id: str | UUID) -> None:
    """Remove durable execution state from the run record."""
    run_uuid = UUID(str(run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return

        parameters = dict(run.parameters or {})
        if EXECUTION_STATE_PARAMETER_KEY in parameters:
            parameters.pop(EXECUTION_STATE_PARAMETER_KEY, None)
            run.parameters = parameters
            flag_modified(run, "parameters")
            await db.commit()


async def _load_persisted_checkpoints(run_id: str | UUID) -> list[RunCheckpoint]:
    """Load durable per-step checkpoints from the run record."""
    run_uuid = UUID(str(run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return []

        parameters = dict(run.parameters or {})
        raw_checkpoints = parameters.get(CHECKPOINTS_PARAMETER_KEY)
        if not isinstance(raw_checkpoints, list):
            return []

        checkpoints: list[RunCheckpoint] = []
        for item in raw_checkpoints:
            if not isinstance(item, dict):
                continue
            try:
                checkpoints.append(RunCheckpoint(**item))
            except Exception:
                continue
        return checkpoints


async def _persist_checkpoint_record(checkpoint: RunCheckpoint) -> None:
    """Persist or replace a durable checkpoint entry on the run record."""
    run_uuid = UUID(str(checkpoint.run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            activity.logger.warning("Unable to persist checkpoint for missing run %s", run_uuid)
            return

        parameters = dict(run.parameters or {})
        raw_checkpoints = parameters.get(CHECKPOINTS_PARAMETER_KEY)
        existing = raw_checkpoints if isinstance(raw_checkpoints, list) else []
        normalized = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            step_name = item.get("step_name")
            if not isinstance(step_name, str):
                continue
            normalized.append(item)

        updated = [item for item in normalized if item.get("step_name") != checkpoint.step_name]
        updated.append(json.loads(checkpoint.model_dump_json()))
        parameters[CHECKPOINTS_PARAMETER_KEY] = updated
        run.parameters = parameters
        flag_modified(run, "parameters")
        await db.commit()


async def _clear_persisted_checkpoints(run_id: str | UUID) -> None:
    """Remove durable checkpoints from the run record."""
    run_uuid = UUID(str(run_id))
    async with _get_sf()() as db:
        stmt = select(Run).where(Run.id == run_uuid)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return

        parameters = dict(run.parameters or {})
        if CHECKPOINTS_PARAMETER_KEY in parameters:
            parameters.pop(CHECKPOINTS_PARAMETER_KEY, None)
            run.parameters = parameters
            flag_modified(run, "parameters")
            await db.commit()


async def _upload_file_to_s3(s3_client, bucket: str, local_path: str, s3_key: str) -> None:
    """Upload a local file to object storage."""
    try:
        await _run_blocking(s3_client.upload_file, local_path, bucket, s3_key)
    except Exception as exc:
        raise_s3_upload_error_with_storage_hint(bucket=bucket, s3_key=s3_key, exc=exc)


async def _download_file_from_s3(s3_client, bucket: str, s3_key: str, local_path: str) -> None:
    """Download a file from object storage."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    await _run_blocking(s3_client.download_file, bucket, s3_key, local_path)


async def _delete_s3_objects(s3_client, bucket: str, s3_keys: list[str]) -> None:
    """Best-effort deletion of durable temporary state objects."""
    for s3_key in s3_keys:
        if not s3_key:
            continue
        try:
            await _run_blocking(s3_client.delete_object, Bucket=bucket, Key=s3_key)
        except Exception as exc:
            activity.logger.warning("Failed to delete temporary state object %s: %s", s3_key, exc)


def _delete_local_paths(paths: list[str | Path | None]) -> None:
    """Best-effort deletion of temporary local pipeline artifacts after upload."""
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Failed to delete temporary local path %s: %s", path, exc)


def _resolve_step_input_snapshot(
    run_id: str | UUID,
    executable_steps: list[dict[str, Any]],
    step_name: str,
    step_outputs: dict[str, str],
    completed_step_names: list[str],
    initial_snapshot_ref: str,
) -> str:
    """Return the durable snapshot reference that should be used as input for a step."""
    step_order = [step["step_name"] for step in executable_steps]
    if step_name not in step_order:
        raise ValueError(f"Step {step_name} is not part of this run definition")

    step_index = step_order.index(step_name)
    completed_step_set = set(completed_step_names)
    prior_completed = [
        candidate for candidate in step_order[:step_index] if candidate in completed_step_set
    ]
    if not prior_completed:
        if not initial_snapshot_ref:
            raise FileNotFoundError(f"Initial snapshot reference not found for run {run_id}")
        return initial_snapshot_ref

    previous_step = prior_completed[-1]
    snapshot_ref = step_outputs.get(previous_step)
    if not snapshot_ref:
        raise FileNotFoundError(f"Committed snapshot for step {previous_step} is missing")
    return snapshot_ref


async def _run_step_in_subprocess(
    *,
    run_id: str | UUID,
    work_dir: str,
    step_name: str,
    input_snapshot_path: str | None,
    output_snapshot_path: str,
    parameters: dict[str, Any],
    random_seed: int,
    raw_downloads: list[dict[str, str]] | None = None,
    expression_sample_labels: list[str] | None = None,
    expression_sample_conditions: list[str] | None = None,
    dataset_condition: str | None = None,
    per_file_upload_metadata: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a scientific step in an isolated child process.

    Returns the step metrics and a small metadata payload describing the committed output.
    """
    import sys

    runtime_dir = Path(work_dir) / "_step_runtime" / step_name
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "config.json"
    result_path = runtime_dir / "result.json"
    stdout_path = runtime_dir / "stdout.log"
    stderr_path = runtime_dir / "stderr.log"

    config = {
        "run_id": str(run_id),
        "step_name": step_name,
        "output_snapshot_path": output_snapshot_path,
        "result_path": str(result_path),
        "parameters": _json_safe(parameters),
        "random_seed": random_seed,
    }
    if input_snapshot_path:
        config["input_snapshot_path"] = input_snapshot_path
    if raw_downloads:
        config["raw_work_dir"] = work_dir
        config["raw_downloads"] = raw_downloads
    if expression_sample_labels:
        config["expression_sample_labels"] = list(expression_sample_labels)
    if expression_sample_conditions:
        config["expression_sample_conditions"] = list(expression_sample_conditions)
    if dataset_condition:
        config["dataset_condition"] = dataset_condition
    if per_file_upload_metadata:
        config["per_file_upload_metadata"] = list(per_file_upload_metadata)
    await _run_blocking(_write_json_file, config_path, config)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cwd = os.getcwd()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else cwd
    # Scrublet + sklearn neighbors + vecLib can oversubscribe threads on Apple Silicon; that
    # correlates with hard exits during doublet scoring. Respect user overrides via setdefault.
    if step_name == "doublet_detection":
        for _thr_key in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            env.setdefault(_thr_key, "1")

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "workflows.run_execution.step_runner",
        str(config_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    logger.info(
        "Spawned scientific subprocess for run %s step %s. stdout=%s stderr=%s",
        run_id,
        step_name,
        stdout_path,
        stderr_path,
    )
    stdout_task = asyncio.create_task(
        _capture_subprocess_stream(
            process.stdout,
            sink_path=stdout_path,
            run_id=run_id,
            step_name=step_name,
            stream_name="stdout",
        )
    )
    stderr_task = asyncio.create_task(
        _capture_subprocess_stream(
            process.stderr,
            sink_path=stderr_path,
            run_id=run_id,
            step_name=step_name,
            stream_name="stderr",
        )
    )
    try:
        await process.wait()
    except asyncio.CancelledError:
        logger.warning(
            "Cancelling scientific subprocess for run %s step %s (pid=%s)",
            run_id,
            step_name,
            getattr(process, "pid", "?"),
        )
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            logger.warning(
                "Scientific subprocess for run %s step %s did not exit after SIGTERM; killing",
                run_id,
                step_name,
            )
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(Exception):
                await process.wait()
        raise
    finally:
        stdout_text = ""
        stderr_text = ""
        if stdout_task and stderr_task:
            stdout_text, stderr_text = await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=False,
            )

    result_payload: dict[str, Any] | None = None
    if result_path.exists():
        result_payload = await _run_blocking(_read_json_file, result_path)

    if process.returncode != 0:
        error_message = None
        if result_payload:
            error_detail = result_payload.get("error")
            traceback_detail = result_payload.get("traceback")
            if error_detail and traceback_detail and traceback_detail != error_detail:
                error_message = f"{error_detail}\n\n{traceback_detail}"
            else:
                error_message = error_detail or traceback_detail
        if not error_message:
            error_message = stderr_text or stdout_text or "scientific subprocess crashed"
        if process.returncode < 0:
            sig = abs(process.returncode)
            oom_hint = ""
            if sig == 9:
                oom_hint = (
                    " Signal 9 (SIGKILL) usually means the OS stopped the process for memory "
                    "(OOM killer) or a hard limit. Try more worker RAM, fewer cells/genes (stricter "
                    "QC / min_cells per gene), keep data sparse, or run on a larger machine."
                )
            error_message = (
                f"scientific subprocess terminated by signal {sig}: {error_message}{oom_hint}"
            )
        raise RuntimeError(error_message)

    if not result_payload:
        raise RuntimeError(f"Scientific subprocess for step '{step_name}' produced no result")

    if not Path(output_snapshot_path).exists():
        raise RuntimeError(
            f"Scientific subprocess for step '{step_name}' did not write {output_snapshot_path}"
        )

    metrics = result_payload.get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError(f"Scientific subprocess for step '{step_name}' returned invalid metrics")

    return metrics, {
        "n_obs": result_payload.get("n_obs"),
        "n_vars": result_payload.get("n_vars"),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "result_path": str(result_path),
    }


def _run_step_in_process(
    *,
    run_id: str | UUID,
    step_name: str,
    input_snapshot_path: str,
    output_snapshot_path: str,
    parameters: dict[str, Any],
    random_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a low-risk scientific step in-process to reduce peak memory pressure."""
    logger.info("Running step %s for run %s in-process", step_name, run_id)
    adata = None
    new_adata = None
    try:
        adata = _read_adata_snapshot(input_snapshot_path)
        new_adata, metrics = _run_step(step_name, adata, parameters, random_seed)
        _prepare_intermediate_snapshot_adata(new_adata)
        _write_adata_snapshot(new_adata, output_snapshot_path)
        return _json_safe(metrics), {
            "n_obs": int(new_adata.n_obs),
            "n_vars": int(new_adata.n_vars),
            "stdout_path": None,
            "stderr_path": None,
            "result_path": None,
        }
    finally:
        if new_adata is not None:
            del new_adata
        if adata is not None:
            del adata
        _release_process_memory(f"in-process step {step_name}")


def _run_loaded_adata_step_in_process(
    *,
    run_id: str | UUID,
    step_name: str,
    adata: ad.AnnData,
    output_snapshot_path: str,
    parameters: dict[str, Any],
    random_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the first in-process step directly on the freshly loaded AnnData."""
    logger.info("Running step %s for run %s on freshly loaded AnnData", step_name, run_id)
    new_adata = None
    try:
        # Release transient loader allocations before the in-process step begins.
        _release_process_memory(f"loaded AnnData before step {step_name}")
        new_adata, metrics = _run_step(step_name, adata, parameters, random_seed)
        _prepare_intermediate_snapshot_adata(new_adata)
        _write_adata_snapshot(new_adata, output_snapshot_path)
        return _json_safe(metrics), {
            "n_obs": int(new_adata.n_obs),
            "n_vars": int(new_adata.n_vars),
            "stdout_path": None,
            "stderr_path": None,
            "result_path": None,
        }
    finally:
        if new_adata is not None and new_adata is not adata:
            del new_adata
        _release_process_memory(f"loaded-adata step {step_name}")


def _run_raw_loaded_step_in_process(
    *,
    run_id: str | UUID,
    step_name: str,
    work_dir: str,
    raw_downloads: list[dict[str, str]],
    output_snapshot_path: str,
    parameters: dict[str, Any],
    random_seed: int,
    expression_sample_labels: list[str] | None = None,
    expression_sample_conditions: list[str] | None = None,
    dataset_condition: str | None = None,
    per_file_upload_metadata: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load raw inputs and execute the first safe step without a second Python process."""
    logger.info("Running raw-loaded step %s for run %s in-process", step_name, run_id)
    adata = None
    new_adata = None
    try:
        downloaded = [
            (str(item["fname"]), str(item["local_path"]))
            for item in raw_downloads
            if isinstance(item, dict)
            and isinstance(item.get("fname"), str)
            and isinstance(item.get("local_path"), str)
        ]
        if not downloaded:
            raise ValueError("No raw dataset downloads were provided to the in-process step")

        adata = _load_adata(
            work_dir,
            downloaded,
            expression_sample_labels=expression_sample_labels,
            expression_sample_conditions=expression_sample_conditions,
            dataset_condition=dataset_condition,
            per_file_upload_metadata=per_file_upload_metadata,
        )
        # 10x/MTX loading can leave large transient allocations behind; trim before QC.
        _release_process_memory(f"raw dataset load before step {step_name}")
        new_adata, metrics = _run_step(step_name, adata, parameters, random_seed)
        _prepare_intermediate_snapshot_adata(new_adata)
        _write_adata_snapshot(new_adata, output_snapshot_path)
        return _json_safe(metrics), {
            "n_obs": int(new_adata.n_obs),
            "n_vars": int(new_adata.n_vars),
            "stdout_path": None,
            "stderr_path": None,
            "result_path": None,
        }
    finally:
        if new_adata is not None and new_adata is not adata:
            del new_adata
        if adata is not None:
            del adata
        _release_process_memory(f"raw-loaded step {step_name}")


@activity.defn
async def resolve_template(input: dict[str, Any]) -> dict[str, Any]:
    """Resolve pipeline template and validate parameters."""
    run_id = input["run_id"]
    template_id = UUID(input["template_id"])
    parameters = input.get("parameters", {})

    activity.logger.info(f"Resolving template {template_id} for run {run_id}")

    async with _get_sf()() as db:
        try:
            stmt = select(Run).where(Run.id == UUID(run_id))
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run is None:
                return {"valid": False, "error": f"Run {run_id} not found"}

            stmt = select(PipelineTemplate).where(
                PipelineTemplate.id == template_id,
                PipelineTemplate.organization_id == run.organization_id,
            )
            result = await db.execute(stmt)
            template = result.scalar_one_or_none()
            if template is None:
                return {"valid": False, "error": f"Template {template_id} not found"}

            pipeline_service = PipelineService(db)
            is_valid, error_message = await pipeline_service.validate_parameters(
                template_id, parameters
            )
            if not is_valid:
                return {"valid": False, "error": f"Parameter validation failed: {error_message}"}

            try:
                methods = await pipeline_service.resolve_methods(template.definition)
            except ValueError as e:
                return {"valid": False, "error": f"Method resolution failed: {str(e)}"}

            activity.logger.info(f"Template {template_id} resolved with {len(methods)} methods")
            resolved_definition = normalize_pipeline_template_definition(
                deepcopy(template.definition)
            )
            return {
                "valid": True,
                "template": {
                    "id": str(template.id),
                    "name": template.name,
                    "version": template.version,
                    "definition": resolved_definition,
                    "methods": methods,
                },
            }
        except Exception as e:
            activity.logger.error(f"Failed to resolve template: {e}")
            return {"valid": False, "error": f"Template resolution error: {str(e)}"}


@activity.defn
async def execute_pipeline(input: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the scRNA-seq pipeline directly in Python using scanpy methods.

    Downloads dataset files from MinIO, loads them into an AnnData object,
    and runs each pipeline step sequentially.
    """
    import scanpy as sc

    run_id = input["run_id"]
    dataset_version_id = UUID(input["dataset_version_id"])
    template = input["template"]
    parameters = input.get("parameters", {})
    random_seed = input.get("random_seed", 42)

    activity.logger.info(
        f"Executing pipeline for run {run_id} with template "
        f"{template['name']} v{template['version']}"
    )
    heartbeat_details: dict[str, Any] = {
        "run_id": run_id,
        "phase": "initializing",
        "current_step": None,
        "completed_steps": [],
        "total_steps": 0,
        "activity_started_monotonic": monotonic(),
    }
    heartbeat_task = asyncio.create_task(_heartbeat_while_running(heartbeat_details))
    pipeline_slot_acquired = False

    # Large steps (e.g. ligand–receptor after densification) write multi-GB H5AD snapshots under
    # this directory. Default is TMPDIR (often /var/folders/... on macOS); set
    # ZERNA_PIPELINE_WORK_ROOT to a path on a spacious volume if you hit errno 28 ENOSPC.
    _work_parent = os.environ.get("ZERNA_PIPELINE_WORK_ROOT", "").strip()
    if _work_parent:
        wp = Path(_work_parent)
        wp.mkdir(parents=True, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix=f"zerna_run_{run_id}_", dir=str(wp))
        activity.logger.info(
            "Pipeline work dir (ZERNA_PIPELINE_WORK_ROOT=%s): %s", _work_parent, work_dir
        )
    else:
        work_dir = tempfile.mkdtemp(prefix=f"zerna_run_{run_id}_")
    adata = None
    activity.logger.info(f"Working directory: {work_dir}")

    try:
        await _acquire_pipeline_slot(run_id, heartbeat_details)
        pipeline_slot_acquired = True

        # --- 1. Download dataset files from MinIO to a temp directory ---
        ds_row: Dataset | None = None
        async with _get_sf()() as db:
            stmt = select(DatasetVersion).where(DatasetVersion.id == dataset_version_id)
            result = await db.execute(stmt)
            dv = result.scalar_one_or_none()
            if dv is None:
                return {
                    "success": False,
                    "error": f"Dataset version {dataset_version_id} not found",
                }

            stmt_ds = select(Dataset).where(Dataset.id == dv.dataset_id)
            ds_row = (await db.execute(stmt_ds)).scalar_one_or_none()

            # Update run status to RUNNING
            stmt = select(Run).where(Run.id == UUID(run_id))
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run:
                run.status = RunStatus.RUNNING
                run.started_at = datetime.utcnow()
                await db.commit()

        dataset_meta = (ds_row.extra_metadata or {}) if ds_row else {}
        raw_labels = dataset_meta.get("expression_sample_labels")
        expression_sample_labels: list[str] | None = None
        if isinstance(raw_labels, list):
            expression_sample_labels = [str(x).strip() for x in raw_labels if str(x).strip()]
        elif isinstance(raw_labels, str) and raw_labels.strip():
            expression_sample_labels = [x.strip() for x in raw_labels.split(",") if x.strip()]
        if expression_sample_labels is not None and len(expression_sample_labels) == 0:
            expression_sample_labels = None
        raw_conds = dataset_meta.get("expression_sample_conditions")
        expression_sample_conditions: list[str] | None = None
        if isinstance(raw_conds, list):
            expression_sample_conditions = [str(x).strip() for x in raw_conds if str(x).strip()]
        elif isinstance(raw_conds, str) and raw_conds.strip():
            expression_sample_conditions = [x.strip() for x in raw_conds.split(",") if x.strip()]
        if expression_sample_conditions is not None and len(expression_sample_conditions) == 0:
            expression_sample_conditions = None
        dc_raw = dataset_meta.get("condition")
        dataset_condition: str | None = (
            str(dc_raw).strip() if dc_raw is not None and str(dc_raw).strip() else None
        )
        raw_pf = dataset_meta.get("per_file_upload_metadata")
        per_file_upload_metadata: list[dict[str, Any]] | None = None
        if isinstance(raw_pf, list) and raw_pf and all(isinstance(x, dict) for x in raw_pf):
            per_file_upload_metadata = [dict(x) for x in raw_pf]

        s3_paths = dv.extra_metadata.get("s3_paths", [])
        if not s3_paths:
            # Fallback: single s3_path field
            s3_paths = [dv.s3_path] if dv.s3_path else []

        s3_bucket = _datasets_bucket_name()
        s3 = _create_s3_client()

        # --- 2. Restore durable execution state and load raw data only when required ---
        methods_list = template["definition"]["methods"]
        executable_steps = _prepare_executable_steps(methods_list, parameters)
        total_steps = len(executable_steps)
        heartbeat_details["total_steps"] = total_steps
        artifacts_bucket = _artifacts_bucket_name()
        execution_state = await _load_execution_state(run_id)

        initial_snapshot_s3_key = str(execution_state.get("initial_snapshot_s3_key") or "")
        adata = None
        downloaded: list[tuple[str, str]] = []
        if initial_snapshot_s3_key:
            activity.logger.info(
                "Found durable initial snapshot for run %s; skipping raw dataset reload.",
                run_id,
            )
        else:
            if not s3_paths:
                return {"success": False, "error": "No files found in dataset version"}

            heartbeat_details["phase"] = "downloading_dataset"
            dset_id_str = str(dv.dataset_id)
            for s3_path in s3_paths:
                logical = _logical_suffix_from_dataset_s3_key(str(s3_path), dset_id_str)
                local_path = _safe_local_path_under_workdir(work_dir, logical)
                parent = os.path.dirname(local_path)
                wd_abs = os.path.abspath(work_dir)
                if parent and os.path.abspath(parent) != wd_abs:
                    os.makedirs(parent, exist_ok=True)
                activity.logger.info(
                    "Downloading s3://%s/%s → %s (logical=%r)",
                    s3_bucket,
                    s3_path,
                    local_path,
                    logical,
                )
                await _run_blocking_with_heartbeats(
                    s3.download_file,
                    s3_bucket,
                    s3_path,
                    local_path,
                    heartbeat_details=heartbeat_details,
                )
                downloaded.append((logical, local_path))
            activity.logger.info(
                "Downloaded %d raw dataset files for run %s; deferring materialization to the first step",
                len(downloaded),
                run_id,
            )

        step_outputs = execution_state.get("step_outputs")
        if not isinstance(step_outputs, dict):
            step_outputs = {}

        step_metrics = execution_state.get("step_metrics")
        if not isinstance(step_metrics, dict):
            step_metrics = {}

        execution_state.update(
            {
                "run_id": str(run_id),
                "dataset_version_id": str(dataset_version_id),
                "template_id": str(template["id"]),
                "template_version": str(template["version"]),
                "initial_snapshot_s3_key": initial_snapshot_s3_key,
                "counts_snapshot_s3_key": _repair_counts_snapshot_s3_key(
                    initial_snapshot_s3_key,
                    step_outputs,
                    str(execution_state.get("counts_snapshot_s3_key") or ""),
                ),
                "step_outputs": step_outputs,
                "step_metrics": step_metrics,
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        await _save_execution_state(run_id, execution_state)
        if adata is not None and initial_snapshot_s3_key:
            del adata
            adata = None
            _release_process_memory("persisting the initial durable snapshot")

        existing_checkpoints = await _load_persisted_checkpoints(run_id)
        completed_step_names = _ordered_unique_steps(
            [
                checkpoint.step_name
                for checkpoint in existing_checkpoints
                if checkpoint.status == RunStatus.COMPLETED
                and checkpoint.step_name in {step["step_name"] for step in executable_steps}
            ]
        )

        if completed_step_names:
            missing_snapshots = [
                step_name for step_name in completed_step_names if not step_outputs.get(step_name)
            ]
            if missing_snapshots:
                activity.logger.warning(
                    "Run %s has checkpoints without durable snapshots for %s; restarting from scratch.",
                    run_id,
                    missing_snapshots,
                )
                await _clear_persisted_checkpoints(run_id)
                completed_step_names = []
                step_outputs = {}
                step_metrics = {}
                execution_state["step_outputs"] = step_outputs
                execution_state["step_metrics"] = step_metrics
                execution_state["updated_at"] = datetime.utcnow().isoformat()
                execution_state["counts_snapshot_s3_key"] = _repair_counts_snapshot_s3_key(
                    initial_snapshot_s3_key,
                    step_outputs,
                    str(execution_state.get("counts_snapshot_s3_key") or ""),
                )
                await _save_execution_state(run_id, execution_state)

        await _update_run_progress(
            run_id,
            total_steps=total_steps,
            completed_steps=completed_step_names,
            progress_percent=round((len(completed_step_names) / total_steps) * 100)
            if total_steps
            else 0,
            state="running",
            clear_current_step=True,
        )

        first_pending_step = executable_steps[0]["step_name"] if executable_steps else None
        for step in executable_steps:
            step_name = step["step_name"]
            step_parameters = step["parameters"]
            if step_name in completed_step_names:
                activity.logger.info(f"Skipping already-completed step: {step_name}")
                continue

            raw_name = step["raw_name"]
            if raw_name != step_name:
                activity.logger.info(
                    f"Running step: {step_name} (from template alias '{raw_name}')"
                )
            else:
                activity.logger.info(f"Running step: {step_name}")
            step_started = datetime.utcnow()
            heartbeat_details["phase"] = "running_pipeline"
            heartbeat_details["current_step"] = step_name
            heartbeat_details["completed_steps"] = list(completed_step_names)
            await _update_run_progress(
                run_id,
                total_steps=total_steps,
                completed_steps=completed_step_names,
                current_step=step_name,
                current_step_started_at=step_started,
                progress_percent=round((len(completed_step_names) / total_steps) * 100)
                if total_steps
                else 0,
                state="running",
            )
            input_snapshot_path: str | None = None
            counts_snapshot_path: str | None = None
            local_cleanup_paths: list[str | Path | None] = []
            try:
                runtime_parameters = dict(step_parameters)
                output_snapshot_path = os.path.join(work_dir, "_step_outputs", f"{step_name}.h5ad")
                if (
                    not initial_snapshot_s3_key
                    and not completed_step_names
                    and not step_outputs
                    and step_name == first_pending_step
                    and downloaded
                ):
                    raw_downloads_payload = [
                        {"fname": fname, "local_path": local_path}
                        for fname, local_path in downloaded
                    ]
                    if step_name in RAW_FIRST_STEP_IN_PROCESS_STEPS:
                        metrics, output_meta = await _run_blocking_with_heartbeats(
                            _run_raw_loaded_step_in_process,
                            run_id=run_id,
                            step_name=step_name,
                            work_dir=work_dir,
                            raw_downloads=raw_downloads_payload,
                            output_snapshot_path=output_snapshot_path,
                            parameters=runtime_parameters,
                            random_seed=random_seed,
                            expression_sample_labels=expression_sample_labels,
                            expression_sample_conditions=expression_sample_conditions,
                            dataset_condition=dataset_condition,
                            per_file_upload_metadata=per_file_upload_metadata,
                            heartbeat_details=heartbeat_details,
                        )
                    else:
                        metrics, output_meta = await _run_step_in_subprocess(
                            run_id=run_id,
                            work_dir=work_dir,
                            step_name=step_name,
                            input_snapshot_path=None,
                            output_snapshot_path=output_snapshot_path,
                            parameters=runtime_parameters,
                            random_seed=random_seed,
                            raw_downloads=raw_downloads_payload,
                            expression_sample_labels=expression_sample_labels,
                            expression_sample_conditions=expression_sample_conditions,
                            dataset_condition=dataset_condition,
                            per_file_upload_metadata=per_file_upload_metadata,
                        )
                    local_cleanup_paths.extend(local_path for _, local_path in downloaded)
                else:
                    input_snapshot_s3_key = _resolve_step_input_snapshot(
                        run_id,
                        executable_steps,
                        step_name,
                        step_outputs,
                        completed_step_names,
                        initial_snapshot_s3_key,
                    )
                    input_snapshot_path = os.path.join(
                        work_dir, "_step_inputs", f"{step_name}.h5ad"
                    )
                    await _download_file_from_s3(
                        s3,
                        artifacts_bucket,
                        input_snapshot_s3_key,
                        input_snapshot_path,
                    )
                    local_cleanup_paths.append(input_snapshot_path)
                    if _step_needs_external_counts(step_name, runtime_parameters):
                        counts_snapshot_s3_key = str(
                            execution_state.get("counts_snapshot_s3_key") or initial_snapshot_s3_key
                        )
                        if counts_snapshot_s3_key:
                            counts_snapshot_path = os.path.join(
                                work_dir, "_counts_refs", f"{step_name}.h5ad"
                            )
                            await _download_file_from_s3(
                                s3,
                                artifacts_bucket,
                                counts_snapshot_s3_key,
                                counts_snapshot_path,
                            )
                            runtime_parameters["counts_snapshot_path"] = counts_snapshot_path
                            local_cleanup_paths.append(counts_snapshot_path)
                    if step_name in IN_PROCESS_STEPS:
                        metrics, output_meta = await _run_blocking_with_heartbeats(
                            _run_step_in_process,
                            run_id=run_id,
                            step_name=step_name,
                            input_snapshot_path=input_snapshot_path,
                            output_snapshot_path=output_snapshot_path,
                            parameters=runtime_parameters,
                            random_seed=random_seed,
                            heartbeat_details=heartbeat_details,
                        )
                    else:
                        metrics, output_meta = await _run_step_in_subprocess(
                            run_id=run_id,
                            work_dir=work_dir,
                            step_name=step_name,
                            input_snapshot_path=input_snapshot_path,
                            output_snapshot_path=output_snapshot_path,
                            parameters=runtime_parameters,
                            random_seed=random_seed,
                        )
                output_snapshot_s3_key = _step_snapshot_s3_key(run_id, step_name)
                await _upload_file_to_s3(
                    s3,
                    artifacts_bucket,
                    output_snapshot_path,
                    output_snapshot_s3_key,
                )
                local_cleanup_paths.append(output_snapshot_path)
                step_metrics[step_name] = metrics
                step_outputs[step_name] = output_snapshot_s3_key
                execution_state["step_outputs"] = step_outputs
                execution_state["step_metrics"] = step_metrics
                execution_state["counts_snapshot_s3_key"] = _repair_counts_snapshot_s3_key(
                    initial_snapshot_s3_key,
                    step_outputs,
                    str(execution_state.get("counts_snapshot_s3_key") or ""),
                )
                execution_state["updated_at"] = datetime.utcnow().isoformat()
                await _save_execution_state(run_id, execution_state)
                activity.logger.info(
                    "Step %s completed. Cells: %s",
                    step_name,
                    output_meta.get("n_obs", "unknown"),
                )
                _raise_if_step_output_empty(step_name, output_meta=output_meta)

                # Persist success checkpoint
                step_completed_at = datetime.utcnow()
                await _persist_checkpoint_record(
                    RunCheckpoint(
                        run_id=UUID(run_id),
                        step_name=step_name,
                        status=RunStatus.COMPLETED,
                        artifact_refs=[output_snapshot_s3_key],
                        started_at=step_started,
                        completed_at=step_completed_at,
                        error_message=None,
                    )
                )
                completed_step_names = _ordered_unique_steps([*completed_step_names, step_name])
                heartbeat_details["completed_steps"] = list(completed_step_names)
                heartbeat_details["current_step"] = None
                await _update_run_progress(
                    run_id,
                    total_steps=total_steps,
                    completed_steps=completed_step_names,
                    progress_percent=round((len(completed_step_names) / total_steps) * 100)
                    if total_steps
                    else 100,
                    state="running",
                    clear_current_step=True,
                    step_entry=_build_step_progress_entry(
                        step_name=step_name,
                        status="completed",
                        started_at=step_started,
                        completed_at=step_completed_at,
                        summary=_format_step_summary(step_name, metrics),
                    ),
                )
                _delete_local_paths(local_cleanup_paths)
            except Exception as step_err:
                activity.logger.error(f"Step {step_name} failed: {step_err}")

                # Persist failure checkpoint
                step_completed_at = datetime.utcnow()
                await _persist_checkpoint_record(
                    RunCheckpoint(
                        run_id=UUID(run_id),
                        step_name=step_name,
                        status=RunStatus.FAILED,
                        artifact_refs=[],
                        started_at=step_started,
                        completed_at=step_completed_at,
                        error_message=str(step_err),
                    )
                )
                error_summary = str(step_err).strip()
                error_summary = error_summary.splitlines()[0] if error_summary else "Step failed."
                heartbeat_details["phase"] = "failed"
                heartbeat_details["current_step"] = None
                await _update_run_progress(
                    run_id,
                    total_steps=total_steps,
                    completed_steps=completed_step_names,
                    progress_percent=round((len(completed_step_names) / total_steps) * 100)
                    if total_steps
                    else 0,
                    state="failed",
                    clear_current_step=True,
                    step_entry=_build_step_progress_entry(
                        step_name=step_name,
                        status="failed",
                        started_at=step_started,
                        completed_at=step_completed_at,
                        summary=error_summary,
                    ),
                )

                return {
                    "success": False,
                    "error": f"Pipeline step '{step_name}' failed: {str(step_err)}",
                    "completed_steps": list(step_metrics.keys()),
                }

        # --- 4. Load final state and materialize artifacts ---
        heartbeat_details["phase"] = "loading_final_state"
        heartbeat_details["current_step"] = None
        if completed_step_names:
            final_snapshot_s3_key = step_outputs[completed_step_names[-1]]
        else:
            final_snapshot_s3_key = initial_snapshot_s3_key

        final_snapshot_path = os.path.join(work_dir, "_state", "final_snapshot.h5ad")
        await _download_file_from_s3(
            s3, artifacts_bucket, final_snapshot_s3_key, final_snapshot_path
        )
        adata = await _run_blocking_with_heartbeats(
            _read_adata_snapshot,
            final_snapshot_path,
            heartbeat_details=heartbeat_details,
        )
        await _run_blocking(_ensure_final_expression_layers, adata)

        from methods.pipeline.provenance import set_run_header

        set_run_header(
            adata,
            {
                "run_id": run_id,
                "template_name": template.get("name"),
                "template_version": template.get("version"),
                "dataset_version_id": str(dataset_version_id),
                "expression_sample_labels": expression_sample_labels,
            },
        )

        heartbeat_details["phase"] = "saving_outputs"
        output_path = os.path.join(work_dir, "processed.h5ad")
        await _run_blocking_with_heartbeats(
            _write_adata_snapshot,
            adata,
            output_path,
            heartbeat_details=heartbeat_details,
        )
        activity.logger.info(f"Saved processed data to {output_path}")

        # --- 5b. Extract and save embedding data as lightweight JSON ---
        import json as _json

        activity.logger.info("%s building embedding JSON (if embeddings present)", FINALIZE_LOG)
        embedding_s3_key = None
        embedding_key = (
            "X_umap" if "X_umap" in adata.obsm else ("X_tsne" if "X_tsne" in adata.obsm else None)
        )
        if embedding_key is not None:
            embedding_coords = adata.obsm[embedding_key]
            obs_names = list(adata.obs_names)
            cluster_column = next(
                (key for key in ("leiden", "cluster", "louvain") if key in adata.obs.columns),
                None,
            )
            clusters = list(adata.obs[cluster_column].astype(str)) if cluster_column else None
            if "annotation_cell_type" in adata.obs.columns:
                cell_types = list(adata.obs["annotation_cell_type"].astype(str))
            elif "annotation_label" in adata.obs.columns:
                cell_types = list(adata.obs["annotation_label"].astype(str))
            elif "celltypist_cell_type" in adata.obs.columns:
                cell_types = list(adata.obs["celltypist_cell_type"].astype(str))
            elif "CellType" in adata.obs.columns:
                cell_types = list(adata.obs["CellType"].astype(str))
            else:
                cell_types = None

            cluster_labels = {}
            cluster_annotations = adata.uns.get("zerna_cluster_annotations")
            if isinstance(cluster_annotations, str):
                try:
                    cluster_annotations = _json.loads(cluster_annotations)
                except Exception:
                    cluster_annotations = {}
            if isinstance(cluster_annotations, dict):
                for cluster_id, annotation in cluster_annotations.items():
                    if not isinstance(annotation, dict):
                        continue
                    label = _first_scalar_annotation_label(annotation)
                    if label:
                        cluster_labels[str(cluster_id)] = label

            if clusters and cell_types:
                counts_by_cluster = {}
                for cluster_id, cell_type in zip(clusters, cell_types, strict=False):
                    if cluster_id in cluster_labels:
                        continue
                    clean_label = str(cell_type).strip()
                    if clean_label == "":
                        continue
                    cluster_counts = counts_by_cluster.setdefault(cluster_id, {})
                    cluster_counts[clean_label] = cluster_counts.get(clean_label, 0) + 1
                for cluster_id, label_counts in counts_by_cluster.items():
                    if not label_counts:
                        continue
                    cluster_labels[cluster_id] = max(
                        label_counts.items(),
                        key=lambda item: (item[1], item[0]),
                    )[0]

            xs = embedding_coords[:, 0]
            ys = embedding_coords[:, 1]
            embedding_json = {
                "embedding_key": embedding_key,
                "cells": [
                    {"id": obs_names[i], "x": round(float(xs[i]), 4), "y": round(float(ys[i]), 4)}
                    for i in range(len(obs_names))
                ],
                "metadata": [
                    {
                        "cellId": obs_names[i],
                        "cluster": clusters[i] if clusters else None,
                        "cellType": cell_types[i] if cell_types else None,
                    }
                    for i in range(len(obs_names))
                ],
                "cluster_labels": cluster_labels,
                "bounds": {
                    "minX": float(xs.min()),
                    "maxX": float(xs.max()),
                    "minY": float(ys.min()),
                    "maxY": float(ys.max()),
                },
                "available_fields": list(
                    dict.fromkeys(
                        (["cluster", cluster_column] if clusters and cluster_column else [])
                        + (["cellType"] if cell_types else [])
                    )
                ),
                "total_cells": len(obs_names),
                "sampled": False,
            }
            emb_path = os.path.join(work_dir, "embedding.json")
            with open(emb_path, "w") as f:
                _json.dump(embedding_json, f)
            embedding_s3_key = f"runs/{run_id}/embedding.json"
            await _upload_file_to_s3(s3, artifacts_bucket, emb_path, embedding_s3_key)
            activity.logger.info(
                f"Uploaded embedding to s3://{artifacts_bucket}/{embedding_s3_key}"
            )

        activity.logger.info("%s entering secondary artifact generation", FINALIZE_LOG)
        additional_artifacts = []
        for artifact in _prepare_secondary_artifacts(
            adata, work_dir, pipeline_step_metrics=step_metrics
        ):
            secondary_s3_key = f"runs/{run_id}/{artifact['relative_key']}"
            await _upload_file_to_s3(s3, artifacts_bucket, artifact["local_path"], secondary_s3_key)
            activity.logger.info(
                f"Uploaded {artifact['artifact_type']} to s3://{artifacts_bucket}/{secondary_s3_key}"
            )
            additional_artifacts.append(
                {
                    "artifact_type": artifact["artifact_type"],
                    "s3_path": secondary_s3_key,
                    "size_bytes": os.path.getsize(artifact["local_path"]),
                    "extra_metadata": artifact.get("extra_metadata", {}),
                }
            )

        activity.logger.info(
            "%s finished staging secondary artifacts for upload (%d)",
            FINALIZE_LOG,
            len(additional_artifacts),
        )

        artifact_s3_key = f"runs/{run_id}/processed.h5ad"
        await _upload_file_to_s3(s3, artifacts_bucket, output_path, artifact_s3_key)
        activity.logger.info(f"Uploaded artifact to s3://{artifacts_bucket}/{artifact_s3_key}")

        output_size = os.path.getsize(output_path)
        state_snapshot_keys = list(
            dict.fromkeys(
                [
                    initial_snapshot_s3_key,
                    *[
                        snapshot_key
                        for snapshot_key in step_outputs.values()
                        if isinstance(snapshot_key, str) and snapshot_key
                    ],
                ]
            )
        )
        await _delete_s3_objects(s3, artifacts_bucket, state_snapshot_keys)
        await _clear_persisted_checkpoints(run_id)
        await _clear_execution_state(run_id)

        result_payload = {
            "success": True,
            "output_path": f"s3://{artifacts_bucket}/runs/{run_id}",
            "artifact_s3_key": artifact_s3_key,
            "artifact_size": output_size,
            "additional_artifacts": additional_artifacts,
            "step_metrics": step_metrics,
            "software_versions": {"scanpy": sc.__version__},
            "cell_count": adata.n_obs,
            "gene_count": adata.n_vars,
        }
        del adata
        adata = None
        _release_process_memory("final artifact materialization")
        return result_payload

    except Exception as e:
        heartbeat_details["phase"] = "failed"
        activity.logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        import shutil

        if adata is not None:
            del adata
            adata = None
        _release_process_memory("execute_pipeline cleanup")
        if pipeline_slot_acquired:
            PIPELINE_ACTIVITY_SEMAPHORE.release()
            logger.info(
                "Run %s released pipeline slot (max_concurrent_pipelines=%d)",
                run_id,
                PIPELINE_ACTIVITY_LIMIT,
            )
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        shutil.rmtree(work_dir, ignore_errors=True)


def _logical_suffix_from_dataset_s3_key(s3_path: str, dataset_id: str) -> str:
    """Return the object path after ``…/datasets/{dataset_id}/`` (may contain ``/``)."""
    needle = f"/datasets/{dataset_id}/"
    if needle not in s3_path:
        return os.path.basename(s3_path)
    return s3_path.split(needle, 1)[1].replace("\\", "/")


def _safe_local_path_under_workdir(work_dir: str, logical_suffix: str) -> str:
    """Join ``logical_suffix`` under ``work_dir``; fall back to basename if traversal is detected."""
    wd = os.path.abspath(work_dir)
    rel = logical_suffix.replace("\\", "/")
    parts = [p for p in rel.split("/") if p]
    for p in parts:
        if p in (".", "..") or ".." in p:
            return os.path.join(wd, os.path.basename(logical_suffix))
    candidate = os.path.normpath(os.path.join(wd, *parts))
    if candidate != wd and not candidate.startswith(wd + os.sep):
        return os.path.join(wd, os.path.basename(logical_suffix))
    return candidate


def _tenx_bundle_partition_group_key(logical_fname: str) -> str:
    """Stable key: folder path first, else filename prefix, else shared bare bucket."""
    norm = logical_fname.replace("\\", "/")
    if "/" in norm:
        return "dir:" + os.path.dirname(norm)
    base = os.path.basename(norm)
    p = _infer_10x_sample_prefix(base)
    if p:
        return "pre:" + p
    return "bare:"


def _format_10x_multi_sample_partition_failure(
    downloaded: list[tuple[str, str]],
    *,
    per_file_upload_metadata: list[dict[str, Any]] | None,
) -> str:
    logical_names = [f for f, _ in downloaded]
    any_slash = any("/" in f.replace("\\", "/") for f in logical_names)
    mtx_basenames = [
        os.path.basename(x) for x in logical_names if _is_matrix_market_file(os.path.basename(x))
    ]
    dup_mtx = sorted({b for b in mtx_basenames if mtx_basenames.count(b) > 1})

    parts: list[str] = [
        "Multiple 10x matrix files were uploaded but the loader could not split them into "
        "separate sample bundles.",
        "Grouping priority is: (1) parent folder in the stored object key when the key contains "
        "a path, (2) a shared filename prefix before matrix/barcodes/features/genes, "
        "(3) otherwise validation fails when multiple bare matrices would share one group.",
    ]
    if not any_slash:
        parts.append(
            "Folder context appears missing: every logical file path is a bare filename with no "
            "directory. Multi-sample GEO-style bundles need nested keys (e.g. GSM123/matrix.mtx.gz). "
            "If the uploader stripped relative paths, enable `file_relative_paths` in the multipart "
            "upload so folder names survive to object storage."
        )
    else:
        parts.append(
            "Some paths include directories; verify each sample uses its own folder or filename "
            "prefix and that matrix/barcodes/features for a sample share that key."
        )
    if dup_mtx:
        parts.append(
            "Duplicate bare matrix filenames with no distinguishing directory or prefix: "
            f"{', '.join(dup_mtx)}."
        )
    if per_file_upload_metadata and len(per_file_upload_metadata) > 1:
        parts.append(
            "Per-file upload metadata lists multiple rows; the detected bundle count must match."
        )
    # Temporary diagnostic: proves this code path is active (remove after worker image verification).
    return " ".join(parts) + " [NEW_HANDLER]"


def _infer_10x_sample_prefix(fname: str) -> str:
    """Return shared prefix for grouped 10x files (e.g. donor1_matrix.mtx → donor1)."""
    import re

    patterns = (
        r"^(.+?)[._-]matrix\.mtx(\.gz)?$",
        r"^(.+?)[._-]barcodes\.tsv(\.gz)?$",
        r"^(.+?)[._-]genes\.tsv(\.gz)?$",
        r"^(.+?)[._-]features\.tsv(\.gz)?$",
    )
    for pat in patterns:
        m = re.match(pat, fname, re.IGNORECASE)
        if m:
            pre = (m.group(1) or "").strip("._- \t")
            if pre:
                return pre
    return ""


def _is_matrix_market_file(fname: str) -> bool:
    fl = fname.lower()
    return fl.endswith(".mtx") or fl.endswith(".mtx.gz")


def _is_10x_bundle_file(fname: str) -> bool:
    base = os.path.basename(fname)
    fl = base.lower()
    return bool(
        _is_matrix_market_file(base)
        or "barcodes" in fl
        or ("genes" in fl and ".tsv" in fl)
        or "features" in fl
    )


def _partition_10x_bundles(downloaded: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Split downloads into separate 10x bundles using folder paths first, then filename prefixes.

    ``downloaded`` entries use logical names (often S3 suffixes under the dataset id), which may
    contain ``/`` when multi-sample MTX was uploaded with preserved relative paths.
    """
    from collections import defaultdict

    mtx_n = sum(1 for f, _ in downloaded if _is_matrix_market_file(os.path.basename(f)))
    if mtx_n <= 1:
        return []

    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for logical_fname, path in downloaded:
        base = os.path.basename(logical_fname)
        if not _is_10x_bundle_file(base):
            continue
        candidates[_tenx_bundle_partition_group_key(logical_fname)].append((logical_fname, path))

    bundles: list[list[tuple[str, str]]] = []
    for key in sorted(candidates.keys()):
        items = candidates[key]
        matrices = [x for x in items if _is_matrix_market_file(os.path.basename(x[0]))]
        if len(matrices) > 1:
            raise ValueError(
                f"Multiple 10x matrix files map to the same bundle group {key!r} "
                f"({len(matrices)} matrices). Use distinct parent folders in stored paths, "
                "distinct filename prefixes (e.g. donor1_matrix.mtx), or upload fewer matrices per run."
                " [NEW_HANDLER]"
            )
        if len(matrices) == 1:
            bundles.append(items)

    if len(bundles) <= 1:
        return []
    return bundles


def _validate_per_file_count(
    label: str,
    per_file_upload_metadata: list[dict[str, Any]] | None,
    n: int,
) -> None:
    if per_file_upload_metadata and len(per_file_upload_metadata) != n:
        raise ValueError(
            f"{label}: per-file upload metadata has {len(per_file_upload_metadata)} entries "
            f"but {n} inputs were detected; counts must match."
        )


def _assign_obs_from_per_file_or_legacy(
    part: ad.AnnData,
    *,
    i: int,
    fname: str,
    label: str,
    row: dict[str, Any] | None,
    conds_override: list[str] | None,
    expression_sample_conditions: list[str] | None = None,
) -> str:
    """Set dataset_name, sample, condition on one AnnData part; return obs_name prefix key."""
    if row:
        dn = str(row.get("dataset_name") or "").strip()
        dataset_name = dn or label
        sid = str(row.get("sample_id") or "").strip()
        sample_val = sid or dataset_name
        cond_cell = str(row.get("condition") or "").strip()
        part.obs["dataset_name"] = dataset_name
        part.obs["sample"] = sample_val
        if conds_override is not None and i < len(conds_override):
            part.obs["condition"] = conds_override[i]
        elif cond_cell:
            part.obs["condition"] = cond_cell
        elif expression_sample_conditions is not None and i < len(expression_sample_conditions):
            part.obs["condition"] = expression_sample_conditions[i]
        else:
            part.obs["condition"] = sample_val
        if str(row.get("tissue") or "").strip():
            part.obs["tissue"] = str(row.get("tissue")).strip()
        if str(row.get("platform") or "").strip():
            part.obs["platform"] = str(row.get("platform")).strip()
        return sample_val
    part.obs["sample"] = label
    if conds_override is not None and i < len(conds_override):
        part.obs["condition"] = conds_override[i]
    else:
        part.obs["condition"] = label
    part.obs["dataset_name"] = label
    return label


def _sanitize_multi_sample_obs_prefix_token(s: str) -> str:
    """ASCII-safe token for obs_name prefixes (file index is added separately for uniqueness)."""
    t = str(s).strip() or "sample"
    out: list[str] = []
    for ch in t[:120]:
        if ch.isalnum() or ch in "-_.+":
            out.append(ch)
        else:
            out.append("_")
    collapsed = "".join(out).strip("_") or "sample"
    return collapsed


def _dedupe_var_index_main_and_raw(
    part: ad.AnnData,
    *,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    """Ensure ``var`` and ``raw.var`` have unique indices before ``ad.concat``.

    ``anndata.concat`` merges ``.var`` (and recursively concats ``.raw``) using pandas
    ``reindex``, which fails on duplicate labels. Main ``AnnData`` exposes
    ``var_names_make_unique``; ``Raw`` does not, so we use ``make_index_unique`` on both.

    When ``dataset_label`` is set, logs a per-part load profile and returns a JSON-serializable
    diagnostics fragment for ``zerna_concat_diagnostics``. When unset (e.g. re-sanitize
    inside ``_concat_adata_axis0_multi``), omits ``[load]`` profile logs and returns ``{}``.
    """
    import pandas as pd
    from anndata.utils import make_index_unique

    n_obs = int(part.n_obs)
    n_vars = int(part.n_vars)
    ix = pd.Index(part.var_names.astype(str))
    var_unique_before = bool(ix.is_unique)
    var_names_deduplicated = not var_unique_before
    had_raw = part.raw is not None
    raw_var_unique_before: bool | None = None
    raw_var_deduplicated = False

    if dataset_label is not None:
        logger.info(
            "[load] dataset=%s n_obs=%d n_vars=%d var_names_unique_before=%s had_raw=%s",
            dataset_label,
            n_obs,
            n_vars,
            var_unique_before,
            had_raw,
        )

    if not ix.is_unique:
        n_dup_entries = int(ix.size - ix.nunique())
        if dataset_label is not None:
            logger.warning(
                "[load] dataset=%s duplicated var_names detected, deduplicating %d entries",
                dataset_label,
                n_dup_entries,
            )
        else:
            logger.warning(
                "Deduplicating %d duplicate var_names on AnnData before concat (unique=%d).",
                int(ix.size),
                int(ix.nunique()),
            )
    part.var_names = make_index_unique(ix)

    if had_raw:
        rix = pd.Index(part.raw.var_names.astype(str))
        raw_var_unique_before = bool(rix.is_unique)
        if dataset_label is not None:
            logger.info(
                "[load] dataset=%s raw.var index unique before sanitation=%s",
                dataset_label,
                raw_var_unique_before,
            )
        if not rix.is_unique:
            raw_var_deduplicated = True
            n_dup_raw = int(rix.size - rix.nunique())
            if dataset_label is not None:
                logger.warning(
                    "[load] dataset=%s raw.var index duplicated, deduplicating %d entries",
                    dataset_label,
                    n_dup_raw,
                )
            else:
                logger.warning(
                    "Deduplicating %d duplicate var_names on AnnData.raw before concat (unique=%d).",
                    int(rix.size),
                    int(rix.nunique()),
                )
            part.raw._var.index = make_index_unique(rix)

    if dataset_label is None:
        return {}

    return {
        "dataset": str(dataset_label),
        "n_obs": n_obs,
        "n_vars": n_vars,
        "var_names_unique_before": var_unique_before,
        "var_names_deduplicated": var_names_deduplicated,
        "had_raw": had_raw,
        "raw_var_unique_before": raw_var_unique_before,
        "raw_var_deduplicated": raw_var_deduplicated,
    }


def _prepare_part_for_multi_sample_concat(
    part: ad.AnnData,
    *,
    file_index: int,
    prefix_key: str,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    """Ensure ``ad.concat(axis=0)`` preconditions: unique ``var_names``; globally unique ``obs_names``.

    ``anndata.concat`` / pandas reindex require unique indices. Duplicate gene symbols within a
    part or identical sample prefixes across uploads (same ``sample_id`` / label) otherwise
    raise ``InvalidIndexError`` / duplicate-label errors.
    """
    label = dataset_label if dataset_label is not None else str(prefix_key)
    diag = _dedupe_var_index_main_and_raw(part, dataset_label=label)
    token = _sanitize_multi_sample_obs_prefix_token(prefix_key)
    prefix = f"s{file_index}_{token}_"
    part.obs_names = [f"{prefix}{x}" for x in part.obs_names.astype(str)]
    part.obs_names_make_unique()
    return diag


def _concat_adata_axis0_multi(
    adatas: list[ad.AnnData],
    *,
    part_load_diagnostics: list[dict[str, Any]] | None = None,
) -> ad.AnnData:
    """Concatenate samples on obs with retries for edge cases (duplicate var / raw)."""
    import anndata as ad

    if not adatas:
        raise ValueError("_concat_adata_axis0_multi: empty AnnData list")

    part_load_diagnostics = part_load_diagnostics or []
    attempts: list[dict[str, Any]] = []
    raw_dropped = False
    final_attempt: int | None = None

    def _deduplicated_inputs_summary() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for d in part_load_diagnostics:
            out.append(
                {
                    "dataset": str(d.get("dataset", "")),
                    "var_names_deduplicated": bool(d.get("var_names_deduplicated", False)),
                    "raw_var_deduplicated": bool(d.get("raw_var_deduplicated", False)),
                }
            )
        return out

    def _attach_uns_diagnostics(adata_out: ad.AnnData, *, succeeded_on: int) -> None:
        adata_out.uns["zerna_concat_diagnostics"] = {
            "n_parts": len(adatas),
            "attempts": attempts,
            "final_attempt": succeeded_on,
            "raw_dropped": raw_dropped,
            "deduplicated_inputs": _deduplicated_inputs_summary(),
        }

    def _log_attempt(n: int, join: str, merge: str, keep_raw: bool) -> None:
        logger.info(
            "[concat] Attempt %d: join=%r, merge=%r, keep_raw=%s",
            n,
            join,
            merge,
            str(keep_raw),
        )

    def _append_attempt(
        n: int,
        join: str,
        merge: str,
        keep_raw: bool,
        *,
        status: str,
        exc: BaseException | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "attempt": n,
            "join": join,
            "merge": merge,
            "keep_raw": keep_raw,
            "status": status,
            "error_type": None,
            "error_message": None,
        }
        if exc is not None:
            entry["error_type"] = type(exc).__name__
            entry["error_message"] = str(exc)
        attempts.append(entry)

    for a in adatas:
        _dedupe_var_index_main_and_raw(a)

    all_obs = []
    for a in adatas:
        all_obs.extend(list(a.obs_names.astype(str)))
    if len(all_obs) != len(set(all_obs)):
        logger.warning(
            "Obs names still collide across %d parts after prefixing; applying emergency uniquify.",
            len(adatas),
        )
        for i, a in enumerate(adatas):
            a.obs_names = [f"__p{i}__{j}__{x}" for j, x in enumerate(a.obs_names.astype(str))]
            a.obs_names_make_unique()

    # Attempt 1: inner + merge=same + keep raw
    _log_attempt(1, "inner", "same", True)
    try:
        out = ad.concat(adatas, axis=0, join="inner", merge="same")
        _append_attempt(1, "inner", "same", True, status="succeeded")
        final_attempt = 1
        _attach_uns_diagnostics(out, succeeded_on=final_attempt)
        return out
    except Exception as exc:
        _append_attempt(1, "inner", "same", True, status="failed", exc=exc)
        logger.warning(
            "[concat] Attempt 1 failed (%s): %s; retrying with merge='unique'",
            type(exc).__name__,
            exc,
        )

    # Attempt 2: inner + merge=unique + keep raw
    _log_attempt(2, "inner", "unique", True)
    try:
        out = ad.concat(adatas, axis=0, join="inner", merge="unique")
        _append_attempt(2, "inner", "unique", True, status="succeeded")
        final_attempt = 2
        _attach_uns_diagnostics(out, succeeded_on=final_attempt)
        return out
    except Exception as exc2:
        _append_attempt(2, "inner", "unique", True, status="failed", exc=exc2)
        logger.warning(
            "[concat] Attempt 2 failed (%s): %s; retrying outer merge='unique'",
            type(exc2).__name__,
            exc2,
        )

    # Attempt 3: outer + merge=unique + keep raw
    _log_attempt(3, "outer", "unique", True)
    try:
        out = ad.concat(adatas, axis=0, join="outer", merge="unique")
        _append_attempt(3, "outer", "unique", True, status="succeeded")
        final_attempt = 3
        _attach_uns_diagnostics(out, succeeded_on=final_attempt)
        return out
    except Exception as exc3:
        _append_attempt(3, "outer", "unique", True, status="failed", exc=exc3)
        logger.warning(
            "[concat] Attempt 3 failed (%s): %s; retrying without .raw on all parts",
            type(exc3).__name__,
            exc3,
        )

    datasets_had_raw: list[str] = []
    for i, a in enumerate(adatas):
        if a.raw is None:
            continue
        if i < len(part_load_diagnostics):
            lab = part_load_diagnostics[i].get("dataset")
            datasets_had_raw.append(str(lab) if lab else f"part_{i}")
        else:
            datasets_had_raw.append(f"part_{i}")
    logger.warning(
        ".raw was removed from input AnnData objects to allow concat to proceed after repeated "
        "index-alignment failures. Datasets that had .raw stripped: %s",
        datasets_had_raw,
    )

    stripped: list[ad.AnnData] = []
    for a in adatas:
        b = a.copy()
        b.raw = None
        stripped.append(b)
    raw_dropped = True

    # Attempt 4: outer + merge=unique + no raw (unchanged strategy)
    _log_attempt(4, "outer", "unique", False)
    try:
        out = ad.concat(stripped, axis=0, join="outer", merge="unique")
        _append_attempt(4, "outer", "unique", False, status="succeeded")
        final_attempt = 4
        _attach_uns_diagnostics(out, succeeded_on=final_attempt)
        return out
    except Exception as exc4:
        _append_attempt(4, "outer", "unique", False, status="failed", exc=exc4)
        logger.error(
            "[concat] All concat attempts failed (last attempt %d: %s: %s). Summary: %s",
            4,
            type(exc4).__name__,
            exc4,
            json.dumps(attempts, default=str),
        )
        raise


def _load_adata(
    work_dir: str,
    downloaded: list,
    *,
    expression_sample_labels: list[str] | None = None,
    expression_sample_conditions: list[str] | None = None,
    dataset_condition: str | None = None,
    per_file_upload_metadata: list[dict[str, Any]] | None = None,
) -> ad.AnnData:
    """Load downloaded files into an AnnData object.

    Multiple CSV/TSV (incl. .gz) count matrices are concatenated along cells (obs);
    use dataset metadata ``expression_sample_labels`` and optional
    ``expression_sample_conditions`` (same order as uploaded files), or file names.
    When ``per_file_upload_metadata`` is set (one dict per file, same order), those
    values populate ``obs['dataset_name']``, ``obs['sample']``, ``obs['condition']``,
    and optional ``obs['tissue']`` / ``obs['platform']`` before concatenation.
    """
    import gzip
    import shutil

    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy import sparse
    from scipy.io import mmread

    def _is_delimited_expression_file(fname: str) -> bool:
        fl = fname.lower()
        return fl.endswith(
            (".csv", ".csv.gz", ".tsv", ".tsv.gz", ".txt", ".txt.gz", ".tab", ".tab.gz")
        )

    def _expression_sample_label_from_filename(fname: str) -> str:
        name = Path(fname).name
        while name.lower().endswith((".gz", ".bz2")):
            name = name[:-3]
        lower = name.lower()
        for ext in (".csv", ".tsv", ".txt", ".tab"):
            if lower.endswith(ext):
                name = name[: -len(ext)]
                lower = name.lower()
                break
        return name.strip() or "sample"

    def _read_delimited_expression(path: str, fname: str) -> ad.AnnData:
        fl = fname.lower()
        if (
            fl.endswith(".tsv")
            or fl.endswith(".tsv.gz")
            or fl.endswith(".tab")
            or fl.endswith(".tab.gz")
        ):
            part = sc.read_text(path, delimiter="\t")
        elif fl.endswith(".txt") or fl.endswith(".txt.gz"):
            part = sc.read_text(path, delimiter=None)
        else:
            part = sc.read_csv(path)
        # Gene-by-barcode CSVs (common *.count*.csv) load as obs=genes, var=cells; transpose.
        if ".count." in fl or "count_matrix" in fl:
            part = part.T
        _dedupe_var_index_main_and_raw(part)
        return part

    def _apply_default_condition(adata_obj: ad.AnnData, cond: str | None) -> None:
        if not cond:
            return
        if "condition" not in adata_obj.obs.columns or adata_obj.obs["condition"].isna().all():
            adata_obj.obs["condition"] = cond

    def _read_metadata_table(path: Path) -> pd.DataFrame:
        name = path.name.lower()
        sep = (
            "\t"
            if name.endswith(".txt") or name.endswith(".tsv") or name.endswith(".tsv.gz")
            else ","
        )
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return pd.read_csv(path, sep=sep, index_col=0, encoding=encoding)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise ValueError(f"Could not read metadata file: {path}")

    def _merge_metadata_into_obs(meta: pd.DataFrame, adata: ad.AnnData, source_name: str) -> bool:
        meta.index = meta.index.astype(str).str.strip()
        obs_names = pd.Series(adata.obs_names).astype(str).str.strip()
        obs_names.index = adata.obs_names
        common = obs_names[obs_names.isin(meta.index)].index
        if len(common) == 0:
            logger.warning(
                "%s found but no cell IDs matched adata.obs_names (sample obs: %s, sample meta: %s)",
                source_name,
                list(obs_names.values[:3]),
                list(meta.index[:3]),
            )
            return False
        for col in meta.columns:
            if col in adata.obs.columns:
                continue
            adata.obs[col] = pd.NA
            adata.obs.loc[common, col] = meta.loc[obs_names.loc[common].values, col].values
        if "condition" not in adata.obs.columns or adata.obs["condition"].isna().all():
            for cond_col in (
                "condition",
                "group",
                "sample_type",
                "disease",
                "orig.ident",
                "sample",
                "batch",
            ):
                if cond_col in adata.obs.columns and adata.obs[cond_col].notna().any():
                    adata.obs["condition"] = adata.obs[cond_col].astype(str)
                    logger.info("Using column '%s' as condition", cond_col)
                    break
        logger.info(
            "Merged %s into adata.obs: %d cells, columns %s",
            source_name,
            len(common),
            list(meta.columns),
        )
        return True

    def _merge_metadata_if_present(dir_path: str | Path, adata: ad.AnnData) -> None:
        dir_path = Path(dir_path)
        for filename in METADATA_FILENAMES:
            candidate = dir_path / filename
            if not candidate.exists():
                continue
            try:
                meta = _read_metadata_table(candidate)
                if _merge_metadata_into_obs(meta, adata, candidate.name):
                    return
            except Exception as exc:
                logger.warning("Failed to merge metadata from %s: %s", candidate, exc)

    def _downcast_sparse_counts_matrix(matrix):
        if not sparse.issparse(matrix):
            return matrix
        if np.issubdtype(matrix.dtype, np.integer):
            info = np.iinfo(np.int32)
            data_min = matrix.data.min(initial=0) if matrix.nnz else 0
            data_max = matrix.data.max(initial=0) if matrix.nnz else 0
            if info.min <= data_min and data_max <= info.max:
                matrix.data = matrix.data.astype(np.int32, copy=False)
                return matrix
        if matrix.dtype != np.float32:
            matrix.data = matrix.data.astype(np.float32, copy=False)
        return matrix

    def _read_10x_mtx_lightweight(dir_path: str | Path) -> ad.AnnData:
        dir_path = Path(dir_path)
        matrix_path = next(
            (
                path
                for path in dir_path.iterdir()
                if path.name.lower().endswith(".mtx") or path.name.lower().endswith(".mtx.gz")
            ),
            None,
        )
        barcodes_path = next(
            (path for path in dir_path.iterdir() if "barcodes" in path.name.lower()),
            None,
        )
        features_path = next(
            (
                path
                for path in dir_path.iterdir()
                if "features" in path.name.lower() or "genes" in path.name.lower()
            ),
            None,
        )
        if matrix_path is None or barcodes_path is None or features_path is None:
            raise ValueError("10x MTX dataset is missing matrix, barcodes, or features/genes files")

        barcodes = pd.read_csv(
            barcodes_path,
            sep="\t",
            header=None,
            compression="infer",
            comment="#",
        )
        features = pd.read_csv(
            features_path,
            sep="\t",
            header=None,
            compression="infer",
            comment="#",
        )

        open_matrix = gzip.open if matrix_path.name.lower().endswith(".gz") else open
        with open_matrix(matrix_path, "rb") as handle:
            matrix = mmread(handle)

        if not sparse.issparse(matrix):
            matrix = sparse.coo_matrix(matrix)
        matrix = matrix.tocsr()

        n_obs = len(barcodes)
        n_var = len(features)
        if matrix.shape == (n_var, n_obs):
            matrix = matrix.transpose().tocsr()
        elif matrix.shape != (n_obs, n_var):
            raise ValueError(
                f"10x MTX shape mismatch: matrix={matrix.shape}, barcodes={n_obs}, features={n_var}"
            )
        matrix = _downcast_sparse_counts_matrix(matrix)

        gene_ids = features.iloc[:, 0].astype(str).fillna("")
        if features.shape[1] > 1:
            gene_symbols = features.iloc[:, 1].astype(str)
        else:
            gene_symbols = gene_ids.copy()
        gene_symbols = gene_symbols.replace({"": pd.NA, "nan": pd.NA}).fillna(gene_ids).astype(str)

        feature_types = None
        if features.shape[1] > 2:
            feature_types = features.iloc[:, 2].astype(str)
            gex_mask = feature_types.eq("Gene Expression")
            if gex_mask.any():
                matrix = matrix[:, gex_mask.to_numpy()]
                gene_ids = gene_ids[gex_mask].reset_index(drop=True)
                gene_symbols = gene_symbols[gex_mask].reset_index(drop=True)
                feature_types = feature_types[gex_mask].reset_index(drop=True)

        obs_names = barcodes.iloc[:, 0].astype(str).str.strip()
        obs = pd.DataFrame(index=obs_names.to_numpy())
        var = pd.DataFrame(index=pd.Index(gene_symbols.to_numpy()))
        var["gene_ids"] = gene_ids.to_numpy()
        if feature_types is not None:
            var["feature_types"] = feature_types.to_numpy()

        adata = ad.AnnData(X=matrix, obs=obs, var=var)
        adata.var["gene_symbols"] = adata.var_names.astype(str)
        adata.var_names_make_unique()
        return adata

    def _load_prepared_10x_mtx_dir(mtx_dir: str, meta_dir: str | None = None) -> ad.AnnData:
        """Load one 10x bundle directory with the same fallbacks as the legacy single-bundle path."""
        meta_root = meta_dir if meta_dir is not None else work_dir
        try:
            adata = _read_10x_mtx_lightweight(mtx_dir)
            _merge_metadata_if_present(meta_root, adata)
            return adata
        except Exception as e:
            logger.warning("Lightweight 10x MTX loader failed: %s", e)
            logger.warning("Falling back to scanpy.read_10x_mtx for compatibility")
        try:
            adata = sc.read_10x_mtx(mtx_dir, var_names="gene_symbols", make_unique=True)
            _merge_metadata_if_present(meta_root, adata)
            return adata
        except Exception as e:
            logger.warning("read_10x_mtx with gene_symbols failed: %s", e)
        try:
            adata = sc.read_10x_mtx(mtx_dir, var_names="gene_ids", make_unique=True)
            if "gene_symbols" in adata.var.columns:
                symbols = adata.var["gene_symbols"].astype(str)
                mask = (symbols == "") | (symbols == "nan") | symbols.isna()
                symbols[mask] = adata.var_names[mask]
                adata.var["ensembl_id"] = adata.var_names.copy()
                adata.var_names = symbols.values
                adata.var_names_make_unique()
                logger.info(
                    "Converted var_names from Ensembl IDs to gene symbols "
                    "(%d mapped, %d kept as Ensembl)",
                    int((~mask).sum()),
                    int(mask.sum()),
                )
            _merge_metadata_if_present(meta_root, adata)
            return adata
        except Exception as e2:
            logger.warning("read_10x_mtx with gene_ids also failed: %s", e2)
            raise ValueError(
                f"Could not load 10x bundle from {mtx_dir}. "
                "Ensure matrix, barcodes, and features/genes files are present and consistent."
            ) from e2

    h5ad_pairs = [(f, p) for f, p in downloaded if f.endswith(".h5ad")]
    if len(h5ad_pairs) > 1:
        _guard_h5ad_memory_budget([path for _, path in h5ad_pairs])
        _validate_per_file_count("Multi-H5AD load", per_file_upload_metadata, len(h5ad_pairs))
        labels_override = expression_sample_labels
        conds_override = expression_sample_conditions
        adatas_h: list[ad.AnnData] = []
        h5ad_part_diags: list[dict[str, Any]] = []
        for i, (fname, path) in enumerate(h5ad_pairs):
            part = sc.read_h5ad(path)
            _merge_metadata_if_present(work_dir, part)
            label = (
                labels_override[i]
                if labels_override is not None and i < len(labels_override)
                else _expression_sample_label_from_filename(fname)
            )
            row = (
                per_file_upload_metadata[i]
                if per_file_upload_metadata and i < len(per_file_upload_metadata)
                else None
            )
            prefix_key = _assign_obs_from_per_file_or_legacy(
                part,
                i=i,
                fname=fname,
                label=label,
                row=row,
                conds_override=conds_override,
                expression_sample_conditions=expression_sample_conditions,
            )
            h5ad_part_diags.append(
                _prepare_part_for_multi_sample_concat(
                    part,
                    file_index=i,
                    prefix_key=str(prefix_key),
                    dataset_label=str(label),
                )
            )
            adatas_h.append(part)
        adata = _concat_adata_axis0_multi(adatas_h, part_load_diagnostics=h5ad_part_diags)
        _merge_metadata_if_present(work_dir, adata)
        _apply_default_condition(adata, dataset_condition)
        return adata

    if len(h5ad_pairs) == 1:
        fname, path = h5ad_pairs[0]
        _guard_h5ad_memory_budget([path])
        adata = sc.read_h5ad(path)
        label = (
            expression_sample_labels[0]
            if expression_sample_labels
            else _expression_sample_label_from_filename(fname)
        )
        _dedupe_var_index_main_and_raw(adata, dataset_label=str(label))
        _merge_metadata_if_present(work_dir, adata)
        row = (
            per_file_upload_metadata[0]
            if per_file_upload_metadata and len(per_file_upload_metadata) >= 1
            else None
        )
        _assign_obs_from_per_file_or_legacy(
            adata,
            i=0,
            fname=fname,
            label=label,
            row=row,
            conds_override=expression_sample_conditions,
            expression_sample_conditions=expression_sample_conditions,
        )
        _apply_default_condition(adata, dataset_condition)
        return adata

    # Check for 10x MTX format (matrix.mtx + barcodes.tsv + genes.tsv/features.tsv.gz)
    has_mtx = any(_is_matrix_market_file(os.path.basename(f)) for f, _ in downloaded)
    has_barcodes = any("barcodes" in os.path.basename(f).lower() for f, _ in downloaded)
    has_genes = any(
        "genes" in os.path.basename(f).lower() or "features" in os.path.basename(f).lower()
        for f, _ in downloaded
    )

    if has_mtx and has_barcodes and (has_genes):
        mtx_n = sum(1 for f, _ in downloaded if _is_matrix_market_file(os.path.basename(f)))
        if mtx_n > 1:
            logger.info(
                "DEBUG_NEW_10X_GROUPING_HANDLER_ACTIVE mtx_n=%d (repo activities.py multi-matrix branch)",
                mtx_n,
            )
        bundles = _partition_10x_bundles(downloaded) if mtx_n > 1 else []

        if (
            mtx_n > 1
            and not bundles
            and per_file_upload_metadata
            and len(per_file_upload_metadata) > 1
        ):
            raise ValueError(
                _format_10x_multi_sample_partition_failure(
                    downloaded,
                    per_file_upload_metadata=per_file_upload_metadata,
                )
            )

        if len(bundles) >= 2:
            _validate_per_file_count(
                "Multi-bundle 10x load", per_file_upload_metadata, len(bundles)
            )
            labels_override = expression_sample_labels
            conds_override = expression_sample_conditions
            parts_10x: list[ad.AnnData] = []
            mtx_part_diags: list[dict[str, Any]] = []
            for i, bundle in enumerate(bundles):
                mtx_dir = os.path.join(work_dir, f"_10x_bundle_{i}")
                os.makedirs(mtx_dir, exist_ok=True)
                for fname, path in bundle:
                    fl = os.path.basename(fname).lower()
                    base = os.path.basename(fname)
                    if (
                        _is_matrix_market_file(base)
                        or "barcodes" in fl
                        or "genes" in fl
                        or "features" in fl
                    ):
                        shutil.copy2(path, os.path.join(mtx_dir, base))
                part = _load_prepared_10x_mtx_dir(mtx_dir, meta_dir=work_dir)
                ref_fname = next(
                    (f for f, _ in bundle if _is_matrix_market_file(os.path.basename(f))),
                    bundle[0][0],
                )
                ref_base = os.path.basename(ref_fname)
                ref_norm = ref_fname.replace("\\", "/")
                folder_sample = (
                    os.path.basename(os.path.dirname(ref_norm)) if "/" in ref_norm else None
                )
                label = (
                    labels_override[i]
                    if labels_override is not None and i < len(labels_override)
                    else (
                        folder_sample
                        if folder_sample
                        else _expression_sample_label_from_filename(ref_base)
                    )
                )
                row = (
                    per_file_upload_metadata[i]
                    if per_file_upload_metadata and i < len(per_file_upload_metadata)
                    else None
                )
                prefix_key = _assign_obs_from_per_file_or_legacy(
                    part,
                    i=i,
                    fname=ref_base,
                    label=label,
                    row=row,
                    conds_override=conds_override,
                    expression_sample_conditions=expression_sample_conditions,
                )
                mtx_part_diags.append(
                    _prepare_part_for_multi_sample_concat(
                        part,
                        file_index=i,
                        prefix_key=str(prefix_key),
                        dataset_label=str(label),
                    )
                )
                parts_10x.append(part)
            adata = _concat_adata_axis0_multi(parts_10x, part_load_diagnostics=mtx_part_diags)
            _merge_metadata_if_present(work_dir, adata)
            _apply_default_condition(adata, dataset_condition)
            return adata

        mtx_dir = os.path.join(work_dir, "_10x")
        os.makedirs(mtx_dir, exist_ok=True)

        for fname, path in downloaded:
            base = os.path.basename(fname)
            fl = base.lower()
            if (
                _is_matrix_market_file(base)
                or "barcodes" in fl
                or "genes" in fl
                or "features" in fl
            ):
                shutil.copy2(path, os.path.join(mtx_dir, base))

        adata = _load_prepared_10x_mtx_dir(mtx_dir, meta_dir=work_dir)
        if per_file_upload_metadata and len(per_file_upload_metadata) == 1:
            ref = next(
                (f for f, _ in downloaded if _is_matrix_market_file(os.path.basename(f))),
                downloaded[0][0],
            )
            ref_norm = ref.replace("\\", "/")
            folder_sample = os.path.basename(os.path.dirname(ref_norm)) if "/" in ref_norm else None
            label = (
                expression_sample_labels[0]
                if expression_sample_labels
                else (
                    folder_sample
                    if folder_sample
                    else _expression_sample_label_from_filename(os.path.basename(ref))
                )
            )
            _assign_obs_from_per_file_or_legacy(
                adata,
                i=0,
                fname=os.path.basename(ref),
                label=label,
                row=per_file_upload_metadata[0],
                conds_override=expression_sample_conditions,
                expression_sample_conditions=expression_sample_conditions,
            )
        elif expression_sample_labels and len(expression_sample_labels) == 1:
            lab = expression_sample_labels[0]
            adata.obs["dataset_name"] = lab
            adata.obs["sample"] = lab
        _apply_default_condition(adata, dataset_condition)
        return adata

    # Check for h5 format
    for fname, path in downloaded:
        if os.path.basename(fname).lower().endswith(".h5"):
            adata = sc.read_10x_h5(path)
            _merge_metadata_if_present(work_dir, adata)
            return adata

    # Check for bare MTX file (incomplete 10x upload — missing barcodes/genes)
    if has_mtx and not (has_barcodes and has_genes):
        missing = []
        if not has_barcodes:
            missing.append("barcodes.tsv")
        if not has_genes:
            missing.append("genes.tsv or features.tsv")
        raise ValueError(
            f"Incomplete 10x MTX upload: found matrix.mtx but missing {', '.join(missing)}. "
            f"Please re-upload with all three files (matrix.mtx, barcodes.tsv, features.tsv.gz)."
        )

    # Delimited expression matrices (CSV/TSV, optional gzip); multiple files → concat on obs
    tabular = [(f, p) for f, p in downloaded if _is_delimited_expression_file(f)]
    if tabular:
        if len(tabular) == 1:
            fname, path = tabular[0]
            adata = _read_delimited_expression(path, fname)
            _merge_metadata_if_present(work_dir, adata)
            label = (
                expression_sample_labels[0]
                if expression_sample_labels
                else _expression_sample_label_from_filename(fname)
            )
            row = (
                per_file_upload_metadata[0]
                if per_file_upload_metadata and len(per_file_upload_metadata) >= 1
                else None
            )
            _assign_obs_from_per_file_or_legacy(
                adata,
                i=0,
                fname=fname,
                label=label,
                row=row,
                conds_override=expression_sample_conditions,
                expression_sample_conditions=expression_sample_conditions,
            )
            _apply_default_condition(adata, dataset_condition)
            return adata
        _validate_per_file_count(
            "Multi-file delimited load", per_file_upload_metadata, len(tabular)
        )
        adatas: list[ad.AnnData] = []
        tabular_part_diags: list[dict[str, Any]] = []
        labels_override = expression_sample_labels
        conds_override = expression_sample_conditions
        for i, (fname, path) in enumerate(tabular):
            part = _read_delimited_expression(path, fname)
            if labels_override is not None and i < len(labels_override):
                label = labels_override[i]
            else:
                label = _expression_sample_label_from_filename(fname)

            row = (
                per_file_upload_metadata[i]
                if per_file_upload_metadata and i < len(per_file_upload_metadata)
                else None
            )
            prefix_key = _assign_obs_from_per_file_or_legacy(
                part,
                i=i,
                fname=fname,
                label=label,
                row=row,
                conds_override=conds_override,
                expression_sample_conditions=expression_sample_conditions,
            )
            tabular_part_diags.append(
                _prepare_part_for_multi_sample_concat(
                    part,
                    file_index=i,
                    prefix_key=str(prefix_key),
                    dataset_label=str(label),
                )
            )
            adatas.append(part)
        adata = _concat_adata_axis0_multi(adatas, part_load_diagnostics=tabular_part_diags)
        _merge_metadata_if_present(work_dir, adata)
        _apply_default_condition(adata, dataset_condition)
        return adata

    raise ValueError(f"Could not determine file format from: {[f for f, _ in downloaded]}")


def _preferred_representation(adata, explicit_rep: str | None = None) -> str | None:
    """Choose the best available embedding for downstream graph construction."""
    if explicit_rep:
        return explicit_rep
    preferred = getattr(adata, "uns", {}).get("zerna_active_representation")
    if isinstance(preferred, str) and preferred in getattr(adata, "obsm", {}):
        return preferred
    for candidate in ("X_scVI", "X_pca_harmony", "X_pca"):
        if candidate in getattr(adata, "obsm", {}):
            return candidate
    return None


def _prepare_annotation_input_adata(adata):
    """Build a slim AnnData for annotation using logged expression values only."""
    if "log1p" in getattr(adata, "layers", {}):
        matrix = adata.layers["log1p"]
        var = adata.var
    elif hasattr(adata, "raw") and adata.raw is not None:
        matrix = adata.raw.X
        var = adata.raw.var
    else:
        matrix = adata.X
        var = adata.var

    return _build_slim_adata(adata, matrix=matrix, var=var)


def _build_slim_adata(adata, *, matrix, var=None, obsm_keys: tuple[str, ...] = ()):
    """Clone only the payload required by a downstream method."""
    slim_var = var.copy() if var is not None else adata.var.copy()
    slim = ad.AnnData(
        X=matrix.copy() if hasattr(matrix, "copy") else matrix,
        obs=adata.obs.copy(),
        var=slim_var,
    )
    slim.obs_names = adata.obs_names.copy()
    slim.var_names = slim_var.index.astype(str)
    for key in obsm_keys:
        if key in getattr(adata, "obsm", {}):
            value = adata.obsm[key]
            slim.obsm[key] = value.copy() if hasattr(value, "copy") else value
    return slim


def _prepare_counts_adata(adata):
    """Return an AnnData view backed by raw counts for count-based methods."""
    if "counts" in getattr(adata, "layers", {}):
        return _build_slim_adata(
            adata,
            matrix=adata.layers["counts"],
            obsm_keys=("X_pca",),
        )
    if hasattr(adata, "raw") and adata.raw is not None:
        counts_adata = _build_slim_adata(
            adata,
            matrix=adata.raw.X,
            var=adata.raw.var,
            obsm_keys=("X_pca", "X_pca_harmony", "X_scVI", "X_umap"),
        )
        return counts_adata
    return adata


def _load_counts_aligned_adata(current_adata, counts_snapshot_path: str):
    """Load a raw-count snapshot and align its annotations to the current state."""
    counts_adata = _read_adata_snapshot(counts_snapshot_path)
    if not counts_adata.obs_names.equals(current_adata.obs_names):
        if not current_adata.obs_names.isin(counts_adata.obs_names).all():
            raise ValueError("Counts snapshot is missing cells required for the current step input")
        counts_adata = counts_adata[current_adata.obs_names, :].copy()
    if not counts_adata.var_names.equals(current_adata.var_names):
        if not current_adata.var_names.isin(counts_adata.var_names).all():
            raise ValueError("Counts snapshot is missing genes required for the current step input")
        counts_adata = counts_adata[:, current_adata.var_names].copy()
    counts_adata.obs = current_adata.obs.copy()
    counts_adata.var = current_adata.var.copy()
    if "counts" not in getattr(counts_adata, "layers", {}):
        counts_adata.layers["counts"] = (
            counts_adata.X.copy() if hasattr(counts_adata.X, "copy") else counts_adata.X
        )
    return counts_adata


def _rank_genes_groups_clusters(adata) -> list[str]:
    """Extract cluster names from scanpy rank_genes_groups output."""
    rank_genes_groups = getattr(adata, "uns", {}).get("rank_genes_groups")
    if not isinstance(rank_genes_groups, dict):
        return []

    names = rank_genes_groups.get("names")
    if names is None:
        return []

    dtype_names = getattr(getattr(names, "dtype", None), "names", None)
    if dtype_names:
        return [str(name) for name in dtype_names]

    if isinstance(names, dict):
        return [str(name) for name in names]

    return []


def _prepare_secondary_artifacts(
    adata,
    work_dir: str,
    *,
    pipeline_step_metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Materialize secondary analysis outputs as exportable files."""
    import json as _json

    import numpy as np
    import pandas as pd

    from methods.pipeline.provenance import build_summary_dict

    artifacts: list[dict[str, Any]] = []
    finalize_stage = "init"

    logger.info("%s entering secondary artifact generation", FINALIZE_LOG)

    try:
        finalize_stage = "differential_expression_export"
        logger.info("%s writing DE export if present", FINALIZE_LOG)
        if "rank_genes_groups" in getattr(adata, "uns", {}):
            from methods.annotation.differential_expression import _extract_de_results

            clusters = _rank_genes_groups_clusters(adata)
            if len(clusters) > 0:
                de_results = _extract_de_results(adata, clusters, 0)
                if not de_results.empty:
                    export_df = de_results.rename(
                        columns={
                            "logfoldchange": "log_fold_change",
                            "pval": "p_value",
                            "pval_adj": "adjusted_p_value",
                        }
                    )
                    de_path = os.path.join(work_dir, "de_results.csv")
                    export_df.to_csv(de_path, index=False)
                    artifacts.append(
                        {
                            "artifact_type": ArtifactType.DE_RESULTS.value,
                            "local_path": de_path,
                            "relative_key": "de_results/de_results.csv",
                            "extra_metadata": {
                                "n_rows": int(len(export_df)),
                                "clusters": clusters,
                            },
                        }
                    )

        finalize_stage = "de_pseudobulk_export"
        logger.info("%s writing pseudobulk DE export if present", FINALIZE_LOG)
        raw_pb = getattr(adata, "uns", {}).get("de_pseudobulk_tidy_records")
        if isinstance(raw_pb, list) and len(raw_pb) > 0:
            pb_df = pd.DataFrame(raw_pb)
            if not pb_df.empty:
                export_pb = pb_df.rename(
                    columns={
                        "logfoldchange": "log_fold_change",
                        "pval": "p_value",
                        "pval_adj": "adjusted_p_value",
                    }
                )
                de_pb_path = os.path.join(work_dir, "de_results_pseudobulk.csv")
                export_pb.to_csv(de_pb_path, index=False)
                artifacts.append(
                    {
                        "artifact_type": ArtifactType.DE_RESULTS.value,
                        "local_path": de_pb_path,
                        "relative_key": "de_results/de_results_pseudobulk.csv",
                        "extra_metadata": {
                            "n_rows": int(len(export_pb)),
                            "kind": "pseudobulk",
                        },
                    }
                )

        finalize_stage = "pathway_scores_export"
        logger.info("%s writing pathway scores if present", FINALIZE_LOG)
        pathway_meta = _uns_mapping_only(getattr(adata, "uns", {}).get("pathway_scoring_meta"))
        pathway_key = str(pathway_meta.get("obsm_key", "pathway_scores"))
        if pathway_key in getattr(adata, "obsm", {}):
            pathway_scores = np.asarray(adata.obsm[pathway_key])
            n_pathways = pathway_scores.shape[1] if pathway_scores.ndim == 2 else 0
            if n_pathways > 0:
                raw_pathway_names = pathway_meta.get("pathway_names")
                pathway_names = (
                    _coerce_str_list(raw_pathway_names, field="pathway_names")
                    if raw_pathway_names is not None
                    else []
                )
                if len(pathway_names) < n_pathways:
                    pathway_names.extend(
                        f"pathway_{idx}" for idx in range(len(pathway_names), n_pathways)
                    )
                pathway_df = pd.DataFrame(
                    pathway_scores,
                    index=adata.obs_names,
                    columns=pathway_names[:n_pathways],
                )
                pathway_df.insert(0, "cell_id", adata.obs_names.astype(str))
                pathway_path = os.path.join(work_dir, "pathway_scores.csv")
                pathway_df.to_csv(pathway_path, index=False)
                artifacts.append(
                    {
                        "artifact_type": ArtifactType.PATHWAY_SCORES.value,
                        "local_path": pathway_path,
                        "relative_key": "pathway_scores/pathway_scores.csv",
                        "extra_metadata": {
                            "n_cells": int(adata.n_obs),
                            "n_pathways": int(n_pathways),
                            "obsm_key": pathway_key,
                        },
                    }
                )

        finalize_stage = "liana_export"
        logger.info("%s writing LIANA results if present", FINALIZE_LOG)
        if "liana_res" in getattr(adata, "uns", {}):
            from methods.annotation.ligand_receptor import _extract_liana_results

            liana_df = _extract_liana_results(adata)
            if not liana_df.empty:
                liana_path = os.path.join(work_dir, "liana_results.csv")
                liana_df.to_csv(liana_path, index=False)
                artifacts.append(
                    {
                        "artifact_type": ArtifactType.LIANA_RESULTS.value,
                        "local_path": liana_path,
                        "relative_key": "liana_results/liana_results.csv",
                        "extra_metadata": {
                            "n_rows": int(len(liana_df)),
                        },
                    }
                )

        finalize_stage = "qc_and_sidecar_summaries"
        logger.info("%s writing QC/de/pathway summaries (qc_report sidecars)", FINALIZE_LOG)
        qc_report = getattr(adata, "uns", {}).get("zerna_qc_report")
        if isinstance(qc_report, dict):
            from methods.preprocessing.qc_filter import expand_zerna_qc_report_for_export

            qc_dir = os.path.join(work_dir, "qc_report")
            os.makedirs(qc_dir, exist_ok=True)
            qc_json_path = os.path.join(qc_dir, "qc_summary.json")
            qc_for_export = expand_zerna_qc_report_for_export(qc_report)
            with open(qc_json_path, "w", encoding="utf-8") as handle:
                _json.dump(_json_safe(qc_for_export), handle, indent=2)
            artifacts.append(
                {
                    "artifact_type": ArtifactType.QC_REPORT.value,
                    "local_path": qc_json_path,
                    "relative_key": "qc_report/qc_summary.json",
                    "extra_metadata": {"kind": "qc_summary"},
                }
            )
            obs_cols = [
                name
                for name in _coerce_str_list(
                    qc_report.get("obs_qc_columns"), field="obs_qc_columns"
                )
                if name in adata.obs.columns
            ]
            if len(obs_cols) > 0:
                qc_csv_path = os.path.join(qc_dir, "qc_metrics.csv")
                adata.obs[obs_cols].to_csv(qc_csv_path)
                artifacts.append(
                    {
                        "artifact_type": ArtifactType.QC_REPORT.value,
                        "local_path": qc_csv_path,
                        "relative_key": "qc_report/qc_metrics.csv",
                        "extra_metadata": {"kind": "qc_metrics", "columns": obs_cols},
                    }
                )

        finalize_stage = "run_summary_json"
        logger.info("%s writing run_summary.json", FINALIZE_LOG)
        summary_payload = _json_safe(build_summary_dict(adata))
        if pipeline_step_metrics is not None:
            summary_payload["step_metrics"] = _json_safe(pipeline_step_metrics)
        summary_dir = os.path.join(work_dir, "qc_report")
        os.makedirs(summary_dir, exist_ok=True)
        summary_path = os.path.join(summary_dir, "run_summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            _json.dump(summary_payload, handle, indent=2)
        artifacts.append(
            {
                "artifact_type": ArtifactType.QC_REPORT.value,
                "local_path": summary_path,
                "relative_key": "qc_report/run_summary.json",
                "extra_metadata": {"kind": "run_summary"},
            }
        )

    except Exception as exc:
        logger.error(
            "%s failed in sub-block %r: %s",
            FINALIZE_LOG,
            finalize_stage,
            exc,
            exc_info=True,
        )
        raise

    logger.info("%s completed secondary artifacts (%d artifacts)", FINALIZE_LOG, len(artifacts))
    return artifacts


def _run_step(step_name: str, adata, parameters: dict, random_seed: int):
    """Run a single pipeline step and return (updated_adata, metrics_dict)."""
    _tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
    if _tl in ("", "tbb"):
        os.environ["NUMBA_THREADING_LAYER"] = "workqueue"
    parameters = _normalize_runtime_parameters(adata, parameters)

    if step_name == "cluster":
        clustering_method = str(parameters.get("clustering_method", "leiden")).strip().lower()
        if clustering_method == "louvain":
            from methods.dimensionality_reduction.clustering import LouvainMethod

            method = LouvainMethod()
        else:
            method = _get_method_instance(step_name)
    elif step_name == "embed":
        embedding_method = str(parameters.get("embedding_method", "umap")).strip().lower()
        if embedding_method == "tsne":
            from methods.dimensionality_reduction.embedding import TSNEMethod

            method = TSNEMethod()
        else:
            method = _get_method_instance(step_name)
    else:
        method = _get_method_instance(step_name)

    original_adata = adata

    # Build step-specific input kwargs from the global parameters
    if step_name == "qc_filter":
        step_input = method.input_schema()(
            adata=adata,
            min_genes=parameters.get("min_genes", 200),
            max_genes=parameters.get("max_genes", 6000),
            min_cells=parameters.get("min_cells", 3),
            max_mito_pct=parameters.get("max_mito_pct", 20.0),
            mito_prefix=parameters.get("mito_prefix", "MT-"),
            min_counts=parameters.get("min_counts"),
            max_counts=parameters.get("max_counts"),
            ribo_prefixes=_parameter_str_list(parameters.get("ribo_prefixes"), ["RPS", "RPL"]),
            max_ribo_pct=parameters.get("max_ribo_pct"),
            hb_gene_names=parameters.get("hb_gene_names"),
            compute_hb_pct=bool(parameters.get("compute_hb_pct", False)),
            max_hb_pct=parameters.get("max_hb_pct"),
            hk_gene_names=parameters.get("hk_gene_names"),
            max_hk_pct=parameters.get("max_hk_pct"),
        )
    elif step_name == "ambient_correction":
        step_input = method.input_schema()(
            adata=adata,
            enabled=bool(parameters.get("ambient_correction", False)),
            method=str(parameters.get("ambient_method", "off")).strip().lower(),
            counts_layer=str(parameters.get("ambient_counts_layer", "counts")),
            corrected_layer=str(parameters.get("ambient_corrected_layer", "corrected_counts")),
            random_state=int(parameters.get("random_seed", 0)),
        )
    elif step_name == "normalize":
        step_input = method.input_schema()(
            adata=adata,
            target_sum=parameters.get("target_sum", 1e4),
            scale=parameters.get("scale", False),
            max_value=parameters.get("max_value", 10.0),
            persist_counts_layer=parameters.get("persist_counts_layer", True),
            source_counts_layer=parameters.get("normalize_source_counts_layer"),
        )
    elif step_name == "select_hvg":
        counts_snapshot_path = parameters.get("counts_snapshot_path")
        if counts_snapshot_path and "counts" not in getattr(adata, "layers", {}):
            adata = _load_counts_aligned_adata(original_adata, str(counts_snapshot_path))
        step_input = method.input_schema()(
            adata=adata,
            n_top_genes=parameters.get("n_top_genes", 2000),
            flavor=parameters.get("hvg_flavor", parameters.get("flavor", "seurat_v3")),
            batch_key=parameters.get("hvg_batch_key", parameters.get("batch_key")),
        )
    elif step_name == "run_pca":
        step_input = method.input_schema()(
            adata=adata,
            n_components=parameters.get("n_pcs", parameters.get("pca_n_components", 50)),
            random_state=random_seed,
        )
    elif step_name == "cluster":
        step_input = method.input_schema()(
            adata=adata,
            resolution=parameters.get("resolution", 1.0),
            n_neighbors=parameters.get("n_neighbors", 15),
            use_rep=_preferred_representation(adata, parameters.get("use_rep")) or "X_pca",
            clustering_method_requested=str(parameters.get("clustering_method", "leiden"))
            .strip()
            .lower(),
            random_state=random_seed,
        )
    elif step_name == "embed":
        use_rep = _preferred_representation(adata, parameters.get("use_rep")) or "X_pca"
        emb_method = str(parameters.get("embedding_method", "umap")).strip().lower()
        step_input = method.input_schema()(
            adata=adata,
            n_components=parameters.get("umap_n_components", parameters.get("n_components", 2)),
            n_neighbors=parameters.get("n_neighbors", 15),
            min_dist=parameters.get("umap_min_dist", parameters.get("min_dist", 0.5)),
            perplexity=parameters.get("tsne_perplexity", parameters.get("perplexity", 30.0)),
            use_rep=use_rep,
            embedding_method_requested=emb_method,
            random_state=random_seed,
        )
    elif step_name == "annotate":
        from methods.annotation.cell_type_annotation import (
            DEFAULT_CELLTYPIST_MODEL_BY_SPECIES,
        )
        from methods.annotation.species import resolve_species

        annotation_method = (
            str(parameters.get("annotation_method", "celltypist")).strip().lower()
        )
        annotation_species = resolve_species(parameters.get("annotation_species"), adata.var_names)
        requested_annotation_model = str(parameters.get("annotation_model", "auto")).strip()
        annotation_model = requested_annotation_model
        if requested_annotation_model.lower() == "custom":
            annotation_model = str(parameters.get("annotation_model_path", "")).strip()
            if not annotation_model:
                return adata, {
                    "skipped": True,
                    "reason": "annotation_model_path is required when annotation_model is custom",
                }
        elif not requested_annotation_model or requested_annotation_model.lower() == "auto":
            annotation_model = DEFAULT_CELLTYPIST_MODEL_BY_SPECIES.get(
                annotation_species,
                DEFAULT_CELLTYPIST_MODEL_BY_SPECIES["human"],
            )

        # Marker-pack-only annotation does not require a CellTypist model overlap preflight.
        try:
            adata_for_ct = _prepare_annotation_input_adata(adata)
            # Keep annotate operating on a slim log-expression AnnData. The step-level
            # merge path copies annotation outputs back onto the main pipeline object,
            # so feeding the full AnnData into agent-v3 only increases temp-file and
            # in-memory pressure without improving results.
            adata_for_annotate = adata_for_ct
            if annotation_method in {
                "celltypist",
                "hybrid",
            }:
                # Check gene overlap with the model before running
                from methods.annotation.cell_type_annotation import _resolve_celltypist_model

                model = _resolve_celltypist_model(annotation_model)
                model_genes = set(model.classifier.features)
                our_genes = set(adata_for_ct.var_names)
                overlap = model_genes & our_genes

                # If overlap is low, try case-insensitive matching first
                # (handles mouse-style "Cd8a" vs human-style "CD8A")
                if len(overlap) < 50:
                    our_upper = {g.upper() for g in adata_for_ct.var_names}
                    model_upper = {g.upper() for g in model_genes}
                    ci_overlap = our_upper & model_upper

                    if len(ci_overlap) >= 50:
                        logger.info(
                            f"Case-sensitive overlap only {len(overlap)}, but "
                            f"case-insensitive overlap is {len(ci_overlap)}. "
                            f"Converting var_names to uppercase to match model."
                        )
                        # Build mapping: model genes are the canonical form
                        model_upper_to_original = {g.upper(): g for g in model_genes}
                        new_names = []
                        for g in adata_for_ct.var_names:
                            gu = str(g).upper()
                            if gu in model_upper_to_original:
                                new_names.append(model_upper_to_original[gu])
                            else:
                                new_names.append(gu)
                        adata_for_ct.var["original_gene_name"] = adata_for_ct.var_names.copy()
                        adata_for_ct.var_names = new_names
                        adata_for_ct.var_names_make_unique()
                        our_genes = set(adata_for_ct.var_names)
                        overlap = model_genes & our_genes
                        logger.info(f"After case normalization: {len(overlap)} gene overlap")

                # If still low, try converting Ensembl IDs to gene symbols
                if len(overlap) < 50 and any(g.startswith("ENSG") for g in list(our_genes)[:100]):
                    logger.info(
                        f"Low gene overlap ({len(overlap)}), detected Ensembl IDs. "
                        f"Attempting conversion to gene symbols."
                    )
                    # Check if gene symbols are stored in .var columns
                    symbol_col = None
                    for col in ["gene_symbols", "gene_symbol", "gene_name", "symbol", "name"]:
                        if col in adata_for_ct.var.columns:
                            symbol_col = col
                            break

                    if symbol_col is not None:
                        symbols = adata_for_ct.var[symbol_col].astype(str)
                        mask = (symbols == "") | (symbols == "nan") | symbols.isna()
                        symbols[mask] = adata_for_ct.var_names[mask]
                        adata_for_ct.var["ensembl_id"] = adata_for_ct.var_names.copy()
                        adata_for_ct.var_names = symbols.values
                        adata_for_ct.var_names_make_unique()
                        # Also update the main adata if different
                        if adata is not adata_for_ct and "ensembl_id" not in adata.var.columns:
                            adata.var["ensembl_id"] = adata.var_names.copy()
                            adata.var_names = symbols.values
                            adata.var_names_make_unique()
                        our_genes = set(adata_for_ct.var_names)
                        overlap = model_genes & our_genes
                        logger.info(f"After symbol conversion: {len(overlap)} gene overlap")

                if len(overlap) < 50:
                    return adata, {
                        "skipped": True,
                        "reason": f"Only {len(overlap)} gene names overlap with model '{annotation_model}' "
                        f"(need ≥50). Dataset may be non-human or use different gene naming.",
                        "gene_overlap": len(overlap),
                        "model_genes": len(model_genes),
                        "dataset_genes": len(our_genes),
                    }

            _ann_ck = str(parameters.get("annotation_cluster_key") or "").strip() or None
            _pipe_ck = str(parameters.get("cluster_key") or "").strip() or None
            step_input = method.input_schema()(
                adata=adata_for_annotate,
                annotation_method=annotation_method,
                model_name=annotation_model,
                majority_voting=parameters.get("annotation_majority_voting", True),
                cluster_key=_ann_ck,
                pipeline_cluster_key_hint=_pipe_ck,
                annotation_input_is_main_adata=(adata_for_annotate is adata),
                min_prob=parameters.get("annotation_min_prob", 0.0),
                knowledge_pack_version=parameters.get("knowledge_pack_version"),
                marker_pack=parameters.get("annotation_marker_pack"),
                marker_pack_path=parameters.get("annotation_marker_pack_path"),
                marker_database=parameters.get("annotation_marker_database", "zerna_default"),
                cluster_prior_path=parameters.get("annotation_cluster_prior_path"),
                tissue_context=parameters.get("annotation_tissue_context", ""),
                cancer_type=parameters.get("annotation_cancer_type"),
                species=annotation_species,
                cluster_marker_top_n=parameters.get("annotation_cluster_marker_top_n", 50),
                min_marker_overlap=parameters.get("annotation_min_marker_overlap", 2),
                benchmark_reference_key=parameters.get("annotation_benchmark_reference_key"),
            )
        except Exception as e:
            import traceback

            logger.error(f"Annotate setup failed: {traceback.format_exc()}")
            return adata, {"skipped": True, "reason": f"annotation setup error: {str(e)}"}
    elif step_name == "doublet_detection":
        dm = parameters.get("doublet_mode")
        if dm is None and parameters.get("filter_doublets") is False:
            dm = "flag_only"
        step_input = method.input_schema()(
            adata=adata,
            method=parameters.get("doublet_method", "scrublet"),
            expected_doublet_rate=parameters.get("expected_doublet_rate", 0.05),
            threshold=parameters.get("doublet_threshold", parameters.get("threshold", 0.25)),
            filter_doublets=parameters.get("filter_doublets", True),
            doublet_mode=dm,
            random_state=random_seed,
            batch_key=parameters.get("batch_key"),
            sample_key=parameters.get("doublet_sample_key"),
            solo_batch_size=parameters.get("solo_batch_size", 512),
            solo_gene_likelihood=parameters.get("solo_gene_likelihood", "zinb"),
            solo_max_epochs=parameters.get("solo_max_epochs", 100),
            doubletdetection_voter_thresh=parameters.get("doubletdetection_voter_thresh", 0.5),
            doubletdetection_p_thresh=parameters.get("doubletdetection_p_thresh", 1e-16),
        )
    elif step_name == "batch_correction_harmony":
        step_input = method.input_schema()(
            adata=adata,
            batch_key=parameters.get("batch_key"),
            n_components=parameters.get("n_pcs", parameters.get("pca_n_components", 50)),
            max_iter_harmony=parameters.get("max_iter_harmony", 10),
            random_state=random_seed,
        )
    elif step_name == "batch_correction_scvi":
        counts_snapshot_path = parameters.get("counts_snapshot_path")
        if counts_snapshot_path and "counts" not in getattr(adata, "layers", {}):
            adata = _load_counts_aligned_adata(original_adata, str(counts_snapshot_path))
        adata = _prepare_counts_adata(adata)
        step_input = method.input_schema()(
            adata=adata,
            batch_key=parameters.get("batch_key"),
            n_latent=parameters.get("n_latent", 30),
            n_layers=parameters.get("n_layers", 2),
            max_epochs=parameters.get("max_epochs") or None,
            random_state=random_seed,
        )
    elif step_name == "differential_expression":
        from methods.annotation.differential_expression import normalize_de_mode

        de_mode = normalize_de_mode(parameters.get("de_mode"))
        gk = parameters.get("de_groupby_key") or parameters.get("cluster_key")
        _de_n_raw = parameters.get("de_n_genes", parameters.get("n_genes", 0))
        _mcs_raw = parameters.get("de_min_cells_per_sample", 10)
        _msg_raw = parameters.get("de_min_samples_per_group", 2)
        _lfc_raw = parameters.get("de_logfc_threshold", 0.0)
        step_input = method.input_schema()(
            adata=adata,
            de_mode=de_mode,
            de_groupby_key=str(gk).strip() if gk else None,
            de_method=parameters.get("de_method", "wilcoxon"),
            de_n_genes=int(_de_n_raw) if _de_n_raw is not None else 0,
            cluster_key=parameters.get("cluster_key", "leiden"),
            de_sample_key=(
                str(parameters.get("de_sample_key")).strip()
                if parameters.get("de_sample_key")
                else None
            ),
            de_condition_key=(
                str(parameters.get("de_condition_key")).strip()
                if parameters.get("de_condition_key")
                else None
            ),
            de_focus_level=(
                str(parameters.get("de_focus_level")).strip()
                if parameters.get("de_focus_level")
                else None
            ),
            de_reference_level=(
                str(parameters.get("de_reference_level")).strip()
                if parameters.get("de_reference_level")
                else None
            ),
            de_compare_level=(
                str(parameters.get("de_compare_level")).strip()
                if parameters.get("de_compare_level")
                else None
            ),
            de_contrast=(
                str(parameters.get("de_contrast")).strip()
                if parameters.get("de_contrast")
                else None
            ),
            de_min_cells_per_sample=int(_mcs_raw) if _mcs_raw is not None else 10,
            de_min_samples_per_group=int(_msg_raw) if _msg_raw is not None else 2,
            de_padj_method=str(parameters.get("de_padj_method", "benjamini-hochberg")),
            de_logfc_threshold=float(_lfc_raw) if _lfc_raw is not None else 0.0,
        )
    elif step_name == "pathway_scoring":
        import pandas as pd

        from methods.annotation.species import resolve_species

        net_path = parameters.get("pathway_net_path")
        pathway_database = str(parameters.get("pathway_database", "PROGENy"))
        pathway_species = resolve_species(parameters.get("annotation_species"), adata.var_names)
        normalized_database = pathway_database.strip().lower()
        if net_path and normalized_database == "custom":
            net = pd.read_csv(net_path)
        else:
            if normalized_database == "custom":
                raise ValueError(
                    "pathway_scoring requires 'pathway_net_path' when pathway_database is 'Custom'"
                )
            else:
                net = _load_builtin_pathway_network(
                    pathway_database,
                    species=pathway_species,
                    progeny_top=int(parameters.get("pathway_progeny_top", 500)),
                )
        step_input = method.input_schema()(
            adata=adata,
            net=net,
            pathway_database=pathway_database,
            knowledge_pack_version=parameters.get("knowledge_pack_version"),
            methods=parameters.get(
                "pathway_methods",
                [parameters.get("pathway_method", "ulm")],
            ),
            min_n=parameters.get("pathway_min_n", 5),
            obsm_key=parameters.get("pathway_obsm_key", "pathway_scores"),
        )
    elif step_name == "ligand_receptor_analysis":
        step_input = method.input_schema()(
            adata=adata,
            communication_grouping=str(
                parameters.get("lr_communication_grouping")
                or parameters.get("communication_grouping")
                or "auto"
            ),
            cluster_key=parameters.get("cluster_key", "leiden"),
            resource_name=parameters.get(
                "lr_resource_name", parameters.get("resource_name", "consensus")
            ),
            expr_prop=parameters.get("lr_expr_prop", parameters.get("expr_prop", 0.1)),
            min_cells=parameters.get("lr_min_cells", parameters.get("min_cells", 5)),
            n_perms=parameters.get("lr_n_perms", parameters.get("n_perms", 100)),
            species=parameters.get("lr_species", parameters.get("annotation_species", "human")),
        )
    else:
        raise ValueError(f"No input mapping for step: {step_name}")

    compute = _build_compute_context(method)
    fallback_metrics: dict[str, Any] = {}
    try:
        with _reserve_compute_slot(compute):
            output = method.execute(step_input, compute)
    except ModuleNotFoundError as exc:
        missing_module = getattr(exc, "name", None)
        if step_name != "batch_correction_scvi" or (
            missing_module != "scvi" and "No module named 'scvi'" not in str(exc)
        ):
            raise

        logger.warning(
            "Batch integration: scVI was requested but importing 'scvi' failed; "
            "executing Harmony instead. Provenance records method_requested=scvi, "
            "method_executed=harmony. Error: %s",
            exc,
        )
        fallback_method = _get_method_instance("batch_correction_harmony")
        fallback_compute = _build_compute_context(fallback_method)
        fallback_input = fallback_method.input_schema()(
            adata=original_adata,
            batch_key=parameters.get("batch_key"),
            n_components=parameters.get("n_pcs", parameters.get("pca_n_components", 50)),
            max_iter_harmony=parameters.get("max_iter_harmony", 10),
            random_state=random_seed,
        )
        with _reserve_compute_slot(fallback_compute):
            output = fallback_method.execute(fallback_input, fallback_compute)
        fallback_metrics = {
            "fallback_method": "harmony",
            "requested_method": "scvi",
            "integration_fallback_applied": True,
            "integration_method_requested": "scvi",
            "integration_method_executed": "harmony",
            "integration_fallback_reason": str(exc),
            "fallback_reason": str(exc),
            "compute_backend": _compute_backend_label(fallback_compute),
            "requested_compute_backend": _compute_backend_label(compute),
        }

    # Extract adata and metrics from output
    new_adata = getattr(output, "adata", adata)

    # For annotate, copy annotation columns back to the main adata
    if step_name == "annotate" and new_adata is not adata:
        for col in [
            "celltypist_cell_type",
            "celltypist_conf_score",
            "celltypist_majority_voting",
            "celltypist_provenance",
            "annotation_tissue",
            "annotation_lineage",
            "annotation_broad",
            "annotation_cell_type",
            "annotation_ontology_id",
            "annotation_hierarchy_path",
            "annotation_confidence",
            "annotation_source",
            "annotation_label",
            "annotation_confidence",
            "annotation_status",
            "annotation_resolution",
            "annotation_uncertainty",
            "annotation_reason",
            "celltype_level1",
            "celltype_level2",
            "celltype_level3",
            "celltype_display",
            "zr_level1",
            "zr_level2",
            "zr_level3",
            "zr_display",
            # Zerna architecture (P1): must persist when annotate returns a new AnnData (e.g. agent v3)
            "auto_level1",
            "auto_level2",
            "auto_level3",
            "final_display",
            "global_cluster",
            "lineage_subcluster",
            "fine_subcluster",
            "level3_final_safe",
            "cci_celltype_major",
            "cci_celltype_minor",
            "cci_celltype_fine",
            "cci_celltype_minor_display",
            "cci_celltype_fine_display",
            "zerna_auto_level3_evidence_source",
            "zerna_auto_level3_evidence_markers",
            "zerna_auto_level3_evidence_lineage",
            "zerna_auto_level3_evidence_fallback",
        ]:
            if col in new_adata.obs.columns:
                adata.obs[col] = new_adata.obs[col]
        if "celltypist_prob_matrix" in new_adata.obsm:
            adata.obsm["celltypist_prob_matrix"] = new_adata.obsm["celltypist_prob_matrix"]
        from methods.annotation.hierarchy_columns import (
            FINE_P3_CONFIG_UNS_KEY,
            FINE_P3_OBSM_KEYS,
            FINE_P3_REPORT_UNS_KEY,
            LINEAGE_P2_CONFIG_UNS_KEY,
            LINEAGE_P2_OBSM_KEYS,
            LINEAGE_P2_REPORT_UNS_KEY,
            ZERNA_LEVEL3_EVIDENCE_UNS_KEY,
            ZERNA_P2_STATUS_UNS_KEY,
            ZERNA_P3_STATUS_UNS_KEY,
        )

        for ok in LINEAGE_P2_OBSM_KEYS:
            if ok in new_adata.obsm:
                adata.obsm[ok] = new_adata.obsm[ok]
        for ok in FINE_P3_OBSM_KEYS:
            if ok in new_adata.obsm:
                adata.obsm[ok] = new_adata.obsm[ok]
        for key in [
            "zerna_cluster_annotations",
            "zerna_annotation",
            "cluster_retrieval_evidence",
            "cluster_markers",
            "cluster_markers_path",
            "conservative_annotation_audit",
            "annotation_benchmark",
            ZERNA_LEVEL3_EVIDENCE_UNS_KEY,
            "explorer_partition_inspector_v1",
            "cluster_marker_evidence_v1",
            "lineage_subcluster_marker_evidence_v1",
            "fine_subcluster_marker_evidence_v1",
            LINEAGE_P2_REPORT_UNS_KEY,
            LINEAGE_P2_CONFIG_UNS_KEY,
            ZERNA_P2_STATUS_UNS_KEY,
            FINE_P3_REPORT_UNS_KEY,
            FINE_P3_CONFIG_UNS_KEY,
            ZERNA_P3_STATUS_UNS_KEY,
        ]:
            if key in new_adata.uns:
                adata.uns[key] = new_adata.uns[key]
        new_adata = adata
    elif step_name == "select_hvg" and new_adata is not original_adata:
        for col in new_adata.var.columns:
            if col.startswith("highly_variable") or col in {
                "means",
                "variances",
                "variances_norm",
                "dispersions",
                "dispersions_norm",
            }:
                original_adata.var[col] = new_adata.var[col].to_numpy()
        new_adata = original_adata
    elif step_name == "batch_correction_scvi" and new_adata is not original_adata:
        for key in ("X_scVI", "X_pca_before"):
            if key in new_adata.obsm:
                original_adata.obsm[key] = new_adata.obsm[key]
        new_adata = original_adata

    metrics = {}
    if hasattr(output, "metrics") and output.metrics is not None:
        metrics = output.metrics.model_dump() if hasattr(output.metrics, "model_dump") else {}
    if hasattr(output, "embedding_key"):
        metrics["embedding_key"] = output.embedding_key
    metrics.setdefault("compute_backend", _compute_backend_label(compute))
    metrics.update(fallback_metrics)

    if step_name == "batch_correction_harmony":
        if resolve_integration_engine(parameters) == "scvi":
            metrics.setdefault("integration_fallback_applied", True)
            metrics.setdefault("integration_method_requested", "scvi")
            metrics.setdefault("integration_method_executed", "harmony")
            metrics.setdefault(
                "integration_fallback_reason",
                "scvi_optional_dependency_unavailable_in_worker",
            )
        finalize_zerna_integration_provenance(
            new_adata,
            executed_engine="harmony",
            parameters=parameters,
            metrics=metrics,
            step_name=step_name,
        )
    elif step_name == "batch_correction_scvi":
        _executed = "harmony" if fallback_metrics.get("fallback_method") == "harmony" else "scvi"
        finalize_zerna_integration_provenance(
            new_adata,
            executed_engine=_executed,
            parameters=parameters,
            metrics=metrics,
            step_name=step_name,
        )

    from methods.pipeline.provenance import append_step

    append_step(new_adata, step_name, {"metrics": _json_safe(metrics)})

    return new_adata, metrics


@activity.defn
async def collect_artifacts(input: dict[str, Any]) -> dict[str, Any]:
    """Collect generated artifacts and create DB records."""
    run_id = UUID(input["run_id"])
    artifact_s3_key = input.get("artifact_s3_key")
    artifact_size = input.get("artifact_size", 0)
    additional_artifacts = input.get("additional_artifacts", [])
    software_versions = input.get("software_versions", {})
    step_metrics = input.get("step_metrics", {})

    activity.logger.info(f"Collecting artifacts for run {run_id}")

    async with _get_sf()() as db:
        try:
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            artifact_ids = []

            if artifact_s3_key:
                artifact = Artifact(
                    id=uuid4(),
                    run_id=run_id,
                    artifact_type=ArtifactType.H5AD,
                    s3_path=artifact_s3_key,
                    size_bytes=artifact_size,
                    extra_metadata={
                        "software_versions": software_versions,
                        "step_metrics": step_metrics,
                    },
                    created_at=datetime.utcnow(),
                )
                db.add(artifact)
                artifact_ids.append(str(artifact.id))

            for artifact_data in additional_artifacts:
                artifact_type = artifact_data.get("artifact_type")
                s3_path = artifact_data.get("s3_path")
                if not artifact_type or not s3_path:
                    continue

                artifact = Artifact(
                    id=uuid4(),
                    run_id=run_id,
                    artifact_type=ArtifactType(artifact_type),
                    s3_path=s3_path,
                    size_bytes=int(artifact_data.get("size_bytes", 0)),
                    extra_metadata=artifact_data.get("extra_metadata", {}),
                    created_at=datetime.utcnow(),
                )
                db.add(artifact)
                artifact_ids.append(str(artifact.id))

            if software_versions:
                run.software_versions = software_versions

            await db.commit()
            activity.logger.info(f"Collected {len(artifact_ids)} artifacts for run {run_id}")

            return {"artifact_ids": artifact_ids, "artifact_count": len(artifact_ids)}

        except Exception as e:
            await db.rollback()
            activity.logger.error(f"Failed to collect artifacts: {e}")
            raise


@activity.defn
async def update_run_status_activity(input: dict[str, Any]) -> dict[str, Any]:
    """
    Final activity: update the run status in the database.

    Called at the end of the workflow to persist the final status
    (COMPLETED or FAILED) so the UI reflects the real state.
    """
    run_id = UUID(input["run_id"])
    new_status = input["status"]  # "completed" or "failed"
    error_message = input.get("error_message")

    activity.logger.info(f"Updating run {run_id} status to {new_status}")

    async with _get_sf()() as db:
        try:
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run is None:
                return {"success": False, "error": f"Run {run_id} not found"}

            run.status = RunStatus(new_status)
            run.completed_at = datetime.utcnow()
            if error_message:
                run.error_message = error_message

            parameters = dict(run.parameters or {})
            progress = parameters.get("progress")
            if not isinstance(progress, dict):
                progress = {}
            progress["state"] = new_status
            progress["current_step"] = None
            progress["current_step_label"] = None
            progress["current_step_started_at"] = None
            total_steps = progress.get("total_steps")
            completed_steps = progress.get("completed_steps")
            if new_status == "completed" and isinstance(total_steps, int) and total_steps > 0:
                progress["progress_percent"] = 100
                if not isinstance(completed_steps, list):
                    progress["completed_steps"] = []
            progress["updated_at"] = datetime.utcnow().isoformat()
            parameters["progress"] = progress
            run.parameters = parameters
            flag_modified(run, "parameters")

            await db.commit()
            activity.logger.info(f"Run {run_id} status updated to {new_status}")
            return {"success": True}

        except Exception as e:
            await db.rollback()
            activity.logger.error(f"Failed to update run status: {e}")
            return {"success": False, "error": str(e)}


@activity.defn
async def cleanup_run_resources(input: dict[str, Any]) -> None:
    """Cleanup resources for a failed or cancelled run (compensation logic)."""
    run_id = UUID(input["run_id"])
    artifact_ids = input.get("artifacts", [])

    activity.logger.info(f"Cleaning up resources for run {run_id}")

    async with _get_sf()() as db:
        try:
            if artifact_ids:
                for artifact_id in artifact_ids:
                    stmt = select(Artifact).where(Artifact.id == UUID(artifact_id))
                    result = await db.execute(stmt)
                    artifact = result.scalar_one_or_none()
                    if artifact:
                        await db.delete(artifact)

            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run and run.status == RunStatus.RUNNING:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.utcnow()
                if not run.error_message:
                    run.error_message = "Run failed and resources were cleaned up"

            await db.commit()
            activity.logger.info(f"Cleanup completed for run {run_id}")

        except Exception as e:
            await db.rollback()
            activity.logger.error(f"Cleanup failed for run {run_id}: {e}")
