"""Batch correction methods: Harmony and scVI for single-cell RNA-seq data."""

from __future__ import annotations

import logging
import os

import anndata as ad
import numpy as np
import scanpy as sc
from zerna_contracts.enums import ComputeBackend, ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition
from methods.data.obs_keys import resolve_batch_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _detect_batch_key(adata: ad.AnnData, batch_key: str | None) -> str | None:
    """Return batch_key if it exists in obs, else auto-detect or return None."""
    return resolve_batch_key(adata, batch_key, strict=batch_key is not None)


def _kbet_score(
    embedding_before: np.ndarray, embedding_after: np.ndarray, batch_labels: np.ndarray
) -> float:
    """Simplified kBET-like score: ratio of within-batch variance reduction.

    Returns a value in [0, 1] where higher means better batch mixing.
    This is a lightweight proxy; full kBET requires R integration.
    """
    unique_batches = np.unique(batch_labels)
    if len(unique_batches) < 2:
        return 1.0

    def within_batch_var(emb: np.ndarray) -> float:
        total = 0.0
        for b in unique_batches:
            mask = batch_labels == b
            if mask.sum() > 1:
                total += float(emb[mask].var(axis=0).mean())
        return total / len(unique_batches)

    var_before = within_batch_var(embedding_before)
    var_after = within_batch_var(embedding_after)
    if var_before == 0:
        return 1.0
    # Lower within-batch variance after correction → better mixing
    return float(np.clip(1.0 - var_after / (var_before + 1e-9), 0.0, 1.0))


def _lisi_score(embedding: np.ndarray, batch_labels: np.ndarray, n_neighbors: int = 15) -> float:
    """Simplified LISI-like score using k-NN batch diversity.

    Returns mean batch diversity in [1, n_batches]; higher = better mixing.
    """
    from sklearn.neighbors import NearestNeighbors

    unique_batches = np.unique(batch_labels)
    n_batches = len(unique_batches)
    if n_batches < 2:
        return float(n_batches)

    k = min(n_neighbors, len(embedding) - 1)
    nbrs = NearestNeighbors(n_neighbors=k, algorithm="auto").fit(embedding)
    _, indices = nbrs.kneighbors(embedding)

    lisi_values = []
    for i, neighbors in enumerate(indices):
        neighbor_batches = batch_labels[neighbors]
        counts = np.bincount(
            np.searchsorted(unique_batches, neighbor_batches),
            minlength=n_batches,
        ).astype(float)
        probs = counts / counts.sum()
        probs = probs[probs > 0]
        # Inverse Simpson index
        lisi_values.append(1.0 / float((probs**2).sum()))

    return float(np.mean(lisi_values))


class BatchCorrectionMetrics(BaseModel):
    batch_key: str
    n_batches: int
    kbet_score: float = Field(description="kBET-like score [0,1]; higher = better mixing")
    lisi_score: float = Field(description="LISI-like score [1, n_batches]; higher = better mixing")
    compute_backend: str | None = None
    accelerator: str | None = None
    requested_compute_backend: str | None = None
    scvi_max_epochs_effective: int | None = None


# ---------------------------------------------------------------------------
# Harmony
# ---------------------------------------------------------------------------


class HarmonyInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    batch_key: str | None = None
    n_components: int = Field(default=50, ge=2)
    random_state: int = 0
    max_iter_harmony: int = 10


class HarmonyOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: BatchCorrectionMetrics


class HarmonyMethod(MethodDefinition):
    """Harmony batch correction operating on PCA embeddings."""

    name = "harmony_batch_correction"
    version = "1.0.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return HarmonyInput

    def output_schema(self):
        return HarmonyOutput

    def execute(self, input: HarmonyInput, compute) -> HarmonyOutput:
        import harmonypy as hm

        adata = input.adata
        batch_key = _detect_batch_key(adata, input.batch_key)

        # Ensure PCA exists
        if "X_pca" not in adata.obsm:
            sc.tl.pca(adata, n_comps=input.n_components, random_state=input.random_state)

        pca_before = adata.obsm["X_pca"].copy()

        if batch_key is None:
            # No batch structure — store original PCA as corrected embedding
            adata.obsm["X_pca_harmony"] = pca_before
            adata.obsm["X_pca_before"] = pca_before
            adata.uns["zerna_integration"] = {
                "method": "harmony",
                "batch_key": None,
                "representation_obsm": "X_pca_harmony",
            }
            adata.uns["zerna_active_representation"] = "X_pca_harmony"
            return HarmonyOutput(
                adata=adata,
                metrics=BatchCorrectionMetrics(
                    batch_key="none",
                    n_batches=1,
                    kbet_score=1.0,
                    lisi_score=1.0,
                ),
            )

        ho = hm.run_harmony(
            pca_before,
            adata.obs,
            batch_key,
            random_state=input.random_state,
            max_iter_harmony=input.max_iter_harmony,
        )
        pca_corrected = np.asarray(ho.Z_corr, dtype=np.float32)
        if pca_corrected.shape != pca_before.shape and pca_corrected.T.shape == pca_before.shape:
            pca_corrected = np.asarray(pca_corrected.T, dtype=np.float32)

        adata.obsm["X_pca_harmony"] = pca_corrected
        adata.obsm["X_pca_before"] = pca_before
        adata.uns["zerna_integration"] = {
            "method": "harmony",
            "batch_key": batch_key,
            "representation_obsm": "X_pca_harmony",
        }
        adata.uns["zerna_active_representation"] = "X_pca_harmony"

        batch_labels = adata.obs[batch_key].astype(str).values
        unique_batches = np.unique(batch_labels)
        # Encode to int for metric helpers
        batch_int = np.searchsorted(unique_batches, batch_labels)

        kbet = _kbet_score(pca_before, pca_corrected, batch_int)
        lisi = _lisi_score(pca_corrected, batch_int)

        return HarmonyOutput(
            adata=adata,
            metrics=BatchCorrectionMetrics(
                batch_key=batch_key,
                n_batches=len(unique_batches),
                kbet_score=kbet,
                lisi_score=lisi,
            ),
        )


# ---------------------------------------------------------------------------
# scVI
# ---------------------------------------------------------------------------


class ScVIInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    batch_key: str | None = None
    n_latent: int = Field(default=30, ge=2)
    n_layers: int = Field(default=2, ge=1)
    max_epochs: int | None = Field(default=None, ge=1)
    random_state: int = 0


class ScVIOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: BatchCorrectionMetrics


class ScVIMethod(MethodDefinition):
    """scVI variational autoencoder batch correction."""

    name = "scvi_batch_correction"
    version = "1.0.1"
    compute_preference = ComputePreference.GPU_PREFERRED
    supported_backends = {
        ComputeBackend.CPU,
        ComputeBackend.CUDA,
        ComputeBackend.ROCM,
        ComputeBackend.METAL,
    }

    def input_schema(self):
        return ScVIInput

    def output_schema(self):
        return ScVIOutput

    def _trainer_kwargs(
        self,
        input: ScVIInput,
        compute,
    ) -> tuple[dict[str, object], str, str]:
        """Map the selected backend to Lightning/scVI trainer arguments."""
        adata = input.adata
        backend = getattr(compute, "selected_backend", None)
        accelerator = "cpu"
        devices: int | str = 1

        if backend in (ComputeBackend.CUDA, ComputeBackend.ROCM):
            accelerator = "gpu"
        elif backend == ComputeBackend.METAL:
            accelerator = "mps"
        else:
            backend = ComputeBackend.CPU

        cpu_count = os.cpu_count() or 1
        if accelerator == "gpu":
            batch_size = 256
            num_workers = min(8, cpu_count)
        elif accelerator == "mps":
            # On macOS, multiprocessing dataloaders can dominate runtime and
            # make long scVI training look stalled. Prefer larger device
            # batches and a small number of persistent workers on the MPS path.
            batch_size = 512
            num_workers = min(2, cpu_count)
        else:
            batch_size = 128
            num_workers = min(2, cpu_count)
        load_sparse_tensor = accelerator == "gpu" and hasattr(adata.X, "tocsr")
        datasplitter_kwargs: dict[str, object] = {"num_workers": num_workers}
        if num_workers > 0:
            datasplitter_kwargs["persistent_workers"] = True

        check_val_every_n_epoch = 1
        if accelerator == "mps":
            check_val_every_n_epoch = 10
        elif accelerator == "cpu":
            check_val_every_n_epoch = 5

        max_epochs = input.max_epochs
        if accelerator == "mps" and max_epochs is None:
            # scVI's default epoch heuristic is tuned for stronger GPU setups.
            # On Apple Metal it can become impractically long without improving
            # the end-to-end product experience, so cap the automatic path.
            max_epochs = 96
            logger.info("Capping automatic scVI epochs to %s on MPS", max_epochs)

        trainer_kwargs: dict[str, object] = {
            "max_epochs": max_epochs,
            "accelerator": accelerator,
            "devices": devices,
            "batch_size": batch_size,
            "load_sparse_tensor": load_sparse_tensor,
            "early_stopping": True,
            "enable_progress_bar": False,
            "check_val_every_n_epoch": check_val_every_n_epoch,
            "datasplitter_kwargs": datasplitter_kwargs,
        }

        return trainer_kwargs, backend.value, accelerator

    @staticmethod
    def _is_mps_sparse_failure(exc: Exception) -> bool:
        """Return whether the exception matches known MPS sparse-tensor failures."""
        message = str(exc).lower()
        return "mps" in message and (
            "new_compressed_tensor" in message
            or "sparse" in message
            or "compressed_tensor" in message
        )

    def execute(self, input: ScVIInput, compute) -> ScVIOutput:
        import scvi

        adata = input.adata
        batch_key = _detect_batch_key(adata, input.batch_key)

        if hasattr(adata.X, "tocsr"):
            adata.X = adata.X.tocsr()

        # scVI requires raw integer counts in X
        scvi.model.SCVI.setup_anndata(adata, batch_key=batch_key)

        requested_backend = getattr(getattr(compute, "selected_backend", None), "value", "cpu")
        trainer_kwargs, backend_label, accelerator = self._trainer_kwargs(input, compute)

        def _build_model():
            return scvi.model.SCVI(
                adata,
                n_latent=input.n_latent,
                n_layers=input.n_layers,
            )

        def _epochs_trained(m) -> int | None:
            hist = getattr(m, "history_", None)
            if isinstance(hist, dict):
                elbo = hist.get("elbo_train")
                if elbo is not None and hasattr(elbo, "__len__"):
                    return int(len(elbo))
            return None

        model = _build_model()
        last_train_kwargs: dict[str, object] = dict(trainer_kwargs)
        try:
            model.train(**trainer_kwargs)
        except Exception as exc:
            if accelerator != "mps" or not self._is_mps_sparse_failure(exc):
                raise

            cpu_kwargs = dict(trainer_kwargs)
            cpu_kwargs.update(
                {
                    "accelerator": "cpu",
                    "devices": 1,
                    "batch_size": 128,
                    "load_sparse_tensor": hasattr(adata.X, "tocsr"),
                    "datasplitter_kwargs": {"num_workers": min(2, os.cpu_count() or 1)},
                }
            )
            model = _build_model()
            model.train(**cpu_kwargs)
            last_train_kwargs = cpu_kwargs
            backend_label = "cpu"
            accelerator = "cpu"

        max_epochs_effective = _epochs_trained(model)
        if max_epochs_effective is None:
            me = last_train_kwargs.get("max_epochs")
            if isinstance(me, int):
                max_epochs_effective = me

        latent = model.get_latent_representation()  # (n_cells, n_latent)
        adata.obsm["X_scVI"] = latent

        # Store a PCA-based "before" embedding for comparison
        if "X_pca" not in adata.obsm:
            sc.tl.pca(adata, n_comps=min(50, adata.n_obs - 1, adata.n_vars - 1))
        adata.obsm["X_pca_before"] = adata.obsm["X_pca"].copy()
        adata.uns["zerna_integration"] = {
            "method": "scvi",
            "batch_key": batch_key,
            "representation_obsm": "X_scVI",
        }
        adata.uns["zerna_active_representation"] = "X_scVI"

        if batch_key is None:
            return ScVIOutput(
                adata=adata,
                metrics=BatchCorrectionMetrics(
                    batch_key="none",
                    n_batches=1,
                    kbet_score=1.0,
                    lisi_score=1.0,
                    compute_backend=backend_label,
                    accelerator=accelerator,
                    requested_compute_backend=requested_backend,
                    scvi_max_epochs_effective=max_epochs_effective,
                ),
            )

        batch_labels = adata.obs[batch_key].astype(str).values
        unique_batches = np.unique(batch_labels)
        batch_int = np.searchsorted(unique_batches, batch_labels)

        pca_before = adata.obsm["X_pca_before"]
        kbet = _kbet_score(pca_before, latent, batch_int)
        lisi = _lisi_score(latent, batch_int)

        return ScVIOutput(
            adata=adata,
            metrics=BatchCorrectionMetrics(
                batch_key=batch_key,
                n_batches=len(unique_batches),
                kbet_score=kbet,
                lisi_score=lisi,
                compute_backend=backend_label,
                accelerator=accelerator,
                requested_compute_backend=requested_backend,
                scvi_max_epochs_effective=max_epochs_effective,
            ),
        )
