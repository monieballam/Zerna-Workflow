"""ComputeContext for hardware detection and backend selection."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from zerna_contracts.enums import ComputeBackend, ComputePreference

if TYPE_CHECKING:
    from zerna_gpu_abstraction.tensor_ops import TensorOps

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class Device:
    """Represents an allocated compute device."""

    backend: ComputeBackend
    device_index: int
    memory_bytes: int


class ComputeContext:
    """Context for managing heterogeneous compute resources.

    Detects available compute backends at runtime and provides
    unified interface for hardware resource management.
    """

    def __init__(self):
        self.available_backends: list[ComputeBackend] = []
        self.selected_backend: ComputeBackend | None = None
        self.device_memory: int = 0
        self.device_count: int = 0

    def detect_hardware(self) -> list[ComputeBackend]:
        """Detect all available compute backends.

        Checks for CUDA, ROCm, Metal, OpenCL, TPU, and CPU availability
        by attempting to import relevant libraries and checking system tools.

        Returns:
            List of available ComputeBackend enums
        """
        backends = []

        # Always available
        backends.append(ComputeBackend.CPU)

        # Detect CUDA (NVIDIA GPUs)
        if self._detect_cuda():
            backends.append(ComputeBackend.CUDA)

        # Detect ROCm (AMD GPUs)
        if self._detect_rocm():
            backends.append(ComputeBackend.ROCM)

        # Detect Metal (Apple Silicon GPUs)
        if self._detect_metal():
            backends.append(ComputeBackend.METAL)

        # Detect OpenCL (Intel and other GPUs)
        if self._detect_opencl():
            backends.append(ComputeBackend.OPENCL)

        # Detect TPU (Google TPUs)
        if self._detect_tpu():
            backends.append(ComputeBackend.TPU)

        self.available_backends = backends
        return backends

    def _detect_cuda(self) -> bool:
        """Detect CUDA availability via nvidia-smi and torch.cuda."""
        # Check nvidia-smi command
        try:
            result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5, check=False)
            if result.returncode != 0:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        # Check torch.cuda availability
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def _detect_rocm(self) -> bool:
        """Detect ROCm availability via rocm-smi and torch with ROCm."""
        # Check rocm-smi command
        try:
            result = subprocess.run(["rocm-smi"], capture_output=True, timeout=5, check=False)
            if result.returncode != 0:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        # Check torch with ROCm support
        try:
            import torch

            # ROCm uses HIP backend in PyTorch
            return hasattr(torch, "hip") and torch.hip.is_available()
        except (ImportError, AttributeError):
            return False

    def _detect_metal(self) -> bool:
        """Detect Metal availability via torch.backends.mps."""
        try:
            import torch

            # Metal Performance Shaders (MPS) backend for Apple Silicon
            return hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        except (ImportError, AttributeError):
            return False

    def _detect_opencl(self) -> bool:
        """Detect OpenCL availability via pyopencl."""
        try:
            import pyopencl as cl

            # Try to get platforms and devices
            platforms = cl.get_platforms()
            if not platforms:
                return False

            # Check if any platform has devices
            for platform in platforms:
                devices = platform.get_devices()
                if devices:
                    return True

            return False
        except (ImportError, Exception):
            return False

    def _detect_tpu(self) -> bool:
        """Detect TPU availability via jax with TPU backend."""
        try:
            import jax

            # Check if JAX can see TPU devices
            devices = jax.devices("tpu")
            return len(devices) > 0
        except (ImportError, RuntimeError, ValueError):
            # RuntimeError or ValueError raised if TPU backend not available
            return False

    def select_backend(self, preference: ComputePreference) -> ComputeBackend:
        """Select optimal backend based on preference and availability.

        Args:
            preference: The compute preference (CPU_ONLY, GPU_PREFERRED, GPU_REQUIRED)

        Returns:
            The selected ComputeBackend

        Raises:
            RuntimeError: If GPU_REQUIRED but no GPU backend is available
        """
        # Ensure hardware has been detected
        if not self.available_backends:
            self.detect_hardware()

        gpu_backends = [b for b in self.available_backends if b != ComputeBackend.CPU]

        if preference == ComputePreference.CPU_ONLY:
            self.selected_backend = ComputeBackend.CPU
            return ComputeBackend.CPU

        if preference == ComputePreference.GPU_REQUIRED:
            if not gpu_backends:
                raise RuntimeError(
                    "GPU_REQUIRED but no GPU backend is available. "
                    f"Available backends: {self.available_backends}"
                )
            self.selected_backend = gpu_backends[0]
            return gpu_backends[0]

        # GPU_PREFERRED: use GPU if available, else CPU
        if gpu_backends:
            self.selected_backend = gpu_backends[0]
            return gpu_backends[0]

        self.selected_backend = ComputeBackend.CPU
        return ComputeBackend.CPU

    def allocate_device(self, memory_required: int) -> Device:
        """Allocate device with sufficient memory.

        Selects the first available device that has at least memory_required bytes.
        Falls back to CPU if no GPU device has sufficient memory.

        Args:
            memory_required: Minimum memory in bytes required for the workload

        Returns:
            A Device with backend, device_index, and memory_bytes

        Raises:
            RuntimeError: If no device has sufficient memory
        """
        if not self.available_backends:
            self.detect_hardware()

        # Try GPU backends first
        gpu_backends = [b for b in self.available_backends if b != ComputeBackend.CPU]

        for backend in gpu_backends:
            available_memory = self._get_device_memory(backend)
            if available_memory >= memory_required:
                return Device(
                    backend=backend,
                    device_index=0,
                    memory_bytes=available_memory,
                )

        # Fall back to CPU (treat as having effectively unlimited memory)
        if ComputeBackend.CPU in self.available_backends:
            cpu_memory = self._get_device_memory(ComputeBackend.CPU)
            if cpu_memory >= memory_required:
                return Device(
                    backend=ComputeBackend.CPU,
                    device_index=0,
                    memory_bytes=cpu_memory,
                )

        raise RuntimeError(f"No device found with at least {memory_required} bytes of memory.")

    def get_tensor_ops(self, backend: ComputeBackend | None = None) -> TensorOps:
        """Return a :class:`TensorOps` instance for *backend*.

        If *backend* is ``None`` the currently selected backend is used.
        Falls back to :class:`CPUTensorOps` when the requested GPU ops
        cannot be instantiated (e.g. missing library).
        """
        from zerna_gpu_abstraction.tensor_ops import (
            CPUTensorOps,
            CUDATensorOps,
            MetalTensorOps,
            OpenCLTensorOps,
            ROCmTensorOps,
            TPUTensorOps,
        )

        backend = backend or self.selected_backend or ComputeBackend.CPU

        _map: dict[ComputeBackend, type] = {
            ComputeBackend.CUDA: CUDATensorOps,
            ComputeBackend.ROCM: ROCmTensorOps,
            ComputeBackend.METAL: MetalTensorOps,
            ComputeBackend.OPENCL: OpenCLTensorOps,
            ComputeBackend.TPU: TPUTensorOps,
            ComputeBackend.CPU: CPUTensorOps,
        }

        cls = _map.get(backend, CPUTensorOps)
        try:
            return cls()
        except ImportError:
            logger.warning("Could not instantiate %s ops, falling back to CPU", backend)
            return CPUTensorOps()

    def execute_with_fallback(
        self,
        fn: Callable[..., T],
        *args: Any,
        preference: ComputePreference = ComputePreference.GPU_PREFERRED,
        **kwargs: Any,
    ) -> tuple[T, ComputeBackend]:
        """Execute *fn* on the preferred backend, falling back to CPU on error.

        *fn* receives a :class:`TensorOps` instance as its first positional
        argument followed by ``*args`` and ``**kwargs``.

        Returns:
            A ``(result, backend_used)`` tuple.

        Raises:
            RuntimeError: Only if *preference* is ``GPU_REQUIRED`` and both
                GPU execution and CPU fallback fail.
        """
        if not self.available_backends:
            self.detect_hardware()

        backend = self.select_backend(preference)
        ops = self.get_tensor_ops(backend)

        try:
            result = fn(ops, *args, **kwargs)
            return result, backend
        except Exception:
            if backend == ComputeBackend.CPU:
                raise  # already on CPU, nothing to fall back to

            if preference == ComputePreference.GPU_REQUIRED:
                raise  # caller explicitly required GPU

            # Fall back to CPU
            logger.warning("Execution on %s failed, falling back to CPU", backend)
            cpu_ops = self.get_tensor_ops(ComputeBackend.CPU)
            result = fn(cpu_ops, *args, **kwargs)
            return result, ComputeBackend.CPU

    def _get_device_memory(self, backend: ComputeBackend) -> int:
        """Return available memory in bytes for the given backend.

        Returns a large sentinel value for CPU (system RAM is not bounded here).
        """
        if backend == ComputeBackend.CPU:
            # Return a large value representing available system memory
            try:
                import psutil

                return psutil.virtual_memory().available
            except ImportError:
                return 2**40  # 1 TiB sentinel

        if backend == ComputeBackend.CUDA:
            try:
                import torch

                if torch.cuda.is_available():
                    free, _ = torch.cuda.mem_get_info(0)
                    return free
            except (ImportError, Exception):
                pass

        if backend in (ComputeBackend.ROCM, ComputeBackend.METAL):
            try:
                import torch

                device = "cuda" if backend == ComputeBackend.ROCM else "mps"
                if backend == ComputeBackend.ROCM and torch.cuda.is_available():
                    free, _ = torch.cuda.mem_get_info(0)
                    return free
            except (ImportError, Exception):
                pass

        # Default: return 0 so the device won't be selected unless it's the only option
        return 0
