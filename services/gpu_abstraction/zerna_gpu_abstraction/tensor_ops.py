"""Unified TensorOps interface for heterogeneous compute backends.

Provides a common abstraction for tensor operations (matmul, svd, knn)
across CUDA, ROCm, Metal, OpenCL, TPU, and CPU backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np

if TYPE_CHECKING:
    import jax
    import pyopencl.array
    import torch

# Type alias for tensors across backends.
# Keep the runtime alias broad so optional backends don't become import-time requirements.
if TYPE_CHECKING:
    Tensor: TypeAlias = np.ndarray | torch.Tensor | jax.Array
else:
    Tensor: TypeAlias = Any


class TensorOps(ABC):
    """Unified interface for tensor operations across compute backends.

    All backend implementations must handle the case where the required
    library is not available by raising ImportError with a descriptive message.
    """

    @abstractmethod
    def matmul(self, a: Tensor, b: Tensor) -> Tensor:
        """Matrix multiplication of tensors a and b.

        Args:
            a: Left-hand tensor of shape (..., m, k)
            b: Right-hand tensor of shape (..., k, n)

        Returns:
            Result tensor of shape (..., m, n)
        """

    @abstractmethod
    def svd(self, a: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        """Singular Value Decomposition of tensor a.

        Args:
            a: Input tensor of shape (m, n)

        Returns:
            Tuple of (U, S, Vh) where a ≈ U @ diag(S) @ Vh
        """

    @abstractmethod
    def knn(self, data: Tensor, k: int) -> Tensor:
        """K-nearest neighbours indices for each point in data.

        Args:
            data: Input tensor of shape (n_samples, n_features)
            k: Number of nearest neighbours to find

        Returns:
            Index tensor of shape (n_samples, k) with neighbour indices
        """


class CPUTensorOps(TensorOps):
    """CPU fallback implementation using numpy."""

    def matmul(self, a: Tensor, b: Tensor) -> np.ndarray:
        return np.matmul(np.asarray(a), np.asarray(b))

    def svd(self, a: Tensor) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return np.linalg.svd(np.asarray(a), full_matrices=False)

    def knn(self, data: Tensor, k: int) -> np.ndarray:
        arr = np.asarray(data)
        n = arr.shape[0]
        # Compute pairwise squared distances via broadcasting
        diff = arr[:, np.newaxis, :] - arr[np.newaxis, :, :]
        dists = np.sum(diff**2, axis=-1)
        # Exclude self (distance 0) by setting diagonal to inf
        np.fill_diagonal(dists, np.inf)
        # Argsort and take first k columns
        indices = np.argsort(dists, axis=1)[:, :k]
        return indices


class CUDATensorOps(TensorOps):
    """CUDA backend using cupy (preferred) or PyTorch with CUDA."""

    def __init__(self) -> None:
        try:
            import cupy  # noqa: F401

            self._backend = "cupy"
        except ImportError:
            try:
                import torch

                if not torch.cuda.is_available():
                    raise ImportError("torch.cuda is not available")
                self._backend = "torch"
            except ImportError as exc:
                raise ImportError(
                    "CUDATensorOps requires cupy or torch with CUDA support. "
                    "Install with: pip install cupy-cuda12x  or  pip install torch"
                ) from exc

    def matmul(self, a: Tensor, b: Tensor) -> Tensor:
        if self._backend == "cupy":
            import cupy as cp

            return cp.matmul(cp.asarray(a), cp.asarray(b))
        import torch

        ta = torch.as_tensor(np.asarray(a)).cuda()
        tb = torch.as_tensor(np.asarray(b)).cuda()
        return torch.matmul(ta, tb)

    def svd(self, a: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        if self._backend == "cupy":
            import cupy as cp

            return cp.linalg.svd(cp.asarray(a), full_matrices=False)
        import torch

        ta = torch.as_tensor(np.asarray(a)).cuda()
        U, S, Vh = torch.linalg.svd(ta, full_matrices=False)
        return U, S, Vh

    def knn(self, data: Tensor, k: int) -> Tensor:
        if self._backend == "cupy":
            import cupy as cp

            arr = cp.asarray(data)
            n = arr.shape[0]
            diff = arr[:, cp.newaxis, :] - arr[cp.newaxis, :, :]
            dists = cp.sum(diff**2, axis=-1)
            cp.fill_diagonal(dists, cp.inf)
            return cp.argsort(dists, axis=1)[:, :k]
        import torch

        arr = torch.as_tensor(np.asarray(data)).cuda()
        dists = torch.cdist(arr, arr)
        dists.fill_diagonal_(float("inf"))
        return torch.argsort(dists, dim=1)[:, :k]


class ROCmTensorOps(TensorOps):
    """ROCm backend using PyTorch with HIP/ROCm support."""

    def __init__(self) -> None:
        try:
            import torch

            if not (hasattr(torch, "hip") and torch.hip.is_available()):
                raise ImportError("torch.hip (ROCm) is not available")
            self._torch = torch
        except ImportError as exc:
            raise ImportError(
                "ROCmTensorOps requires PyTorch built with ROCm support. "
                "See https://pytorch.org/get-started/locally/ for ROCm builds."
            ) from exc

    def _to_device(self, arr: Tensor) -> torch.Tensor:
        import torch

        return torch.as_tensor(np.asarray(arr)).to("cuda")  # ROCm uses 'cuda' device alias

    def matmul(self, a: Tensor, b: Tensor) -> Tensor:
        return self._torch.matmul(self._to_device(a), self._to_device(b))

    def svd(self, a: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        ta = self._to_device(a)
        U, S, Vh = self._torch.linalg.svd(ta, full_matrices=False)
        return U, S, Vh

    def knn(self, data: Tensor, k: int) -> Tensor:
        arr = self._to_device(data)
        dists = self._torch.cdist(arr, arr)
        dists.fill_diagonal_(float("inf"))
        return self._torch.argsort(dists, dim=1)[:, :k]


class MetalTensorOps(TensorOps):
    """Metal backend using PyTorch with MPS (Metal Performance Shaders)."""

    def __init__(self) -> None:
        try:
            import torch

            if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
                raise ImportError("torch.backends.mps (Metal) is not available")
            self._torch = torch
            self._device = torch.device("mps")
        except ImportError as exc:
            raise ImportError(
                "MetalTensorOps requires PyTorch with Metal Performance Shaders (MPS) support. "
                "Requires macOS 12.3+ with Apple Silicon or AMD GPU."
            ) from exc

    def _to_device(self, arr: Tensor) -> torch.Tensor:
        return self._torch.as_tensor(np.asarray(arr, dtype=np.float32)).to(self._device)

    def matmul(self, a: Tensor, b: Tensor) -> Tensor:
        return self._torch.matmul(self._to_device(a), self._to_device(b))

    def svd(self, a: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        ta = self._to_device(a)
        U, S, Vh = self._torch.linalg.svd(ta, full_matrices=False)
        return U, S, Vh

    def knn(self, data: Tensor, k: int) -> Tensor:
        arr = self._to_device(data)
        dists = self._torch.cdist(arr, arr)
        dists.fill_diagonal_(float("inf"))
        return self._torch.argsort(dists, dim=1)[:, :k]


class OpenCLTensorOps(TensorOps):
    """OpenCL backend using pyopencl."""

    def __init__(self) -> None:
        try:
            import pyopencl as cl
            import pyopencl.array as cl_array

            platforms = cl.get_platforms()
            if not platforms:
                raise ImportError("No OpenCL platforms found")
            devices = platforms[0].get_devices()
            if not devices:
                raise ImportError("No OpenCL devices found")
            self._ctx = cl.Context(devices=[devices[0]])
            self._queue = cl.CommandQueue(self._ctx)
            self._cl = cl
            self._cl_array = cl_array
        except ImportError as exc:
            raise ImportError(
                "OpenCLTensorOps requires pyopencl with at least one OpenCL platform/device. "
                "Install with: pip install pyopencl"
            ) from exc

    def _to_device(self, arr: Tensor) -> pyopencl.array.Array:
        return self._cl_array.to_device(self._queue, np.asarray(arr, dtype=np.float32))

    def matmul(self, a: Tensor, b: Tensor) -> np.ndarray:
        # pyopencl.array supports @ operator for 2-D matmul
        ta = self._to_device(a)
        tb = self._to_device(b)
        result = self._cl_array.dot(ta, tb)
        return result.get()

    def svd(self, a: Tensor) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # pyopencl does not provide SVD; fall back to numpy on host
        return np.linalg.svd(np.asarray(a, dtype=np.float32), full_matrices=False)

    def knn(self, data: Tensor, k: int) -> np.ndarray:
        # Compute distances on device, retrieve indices on host
        arr = self._to_device(data)
        arr_np = arr.get()
        diff = arr_np[:, np.newaxis, :] - arr_np[np.newaxis, :, :]
        dists = np.sum(diff**2, axis=-1)
        np.fill_diagonal(dists, np.inf)
        return np.argsort(dists, axis=1)[:, :k]


class TPUTensorOps(TensorOps):
    """TPU backend using JAX."""

    def __init__(self) -> None:
        try:
            import jax
            import jax.numpy as jnp

            devices = jax.devices("tpu")
            if not devices:
                raise ImportError("No JAX TPU devices found")
            self._jax = jax
            self._jnp = jnp
        except (ImportError, RuntimeError, ValueError) as exc:
            raise ImportError(
                "TPUTensorOps requires JAX with TPU backend. Install with: pip install jax[tpu]"
            ) from exc

    def matmul(self, a: Tensor, b: Tensor) -> jax.Array:
        return self._jnp.matmul(self._jnp.asarray(a), self._jnp.asarray(b))

    def svd(self, a: Tensor) -> tuple[jax.Array, jax.Array, jax.Array]:
        return self._jnp.linalg.svd(self._jnp.asarray(a), full_matrices=False)

    def knn(self, data: Tensor, k: int) -> jax.Array:
        arr = self._jnp.asarray(data)
        # Pairwise squared distances
        diff = arr[:, self._jnp.newaxis, :] - arr[self._jnp.newaxis, :, :]
        dists = self._jnp.sum(diff**2, axis=-1)
        # Mask self-distances
        n = arr.shape[0]
        dists = dists.at[self._jnp.arange(n), self._jnp.arange(n)].set(self._jnp.inf)
        return self._jnp.argsort(dists, axis=1)[:, :k]
