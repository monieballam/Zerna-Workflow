"""Unit tests for ComputeContext backend selection logic (task 8.3).

Tests cover select_backend and allocate_device methods for all
ComputePreference values and edge cases.
"""

import pytest
from zerna_contracts.enums import ComputeBackend, ComputePreference
from zerna_gpu_abstraction.compute_context import ComputeContext, Device

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_with_backends(*backends: ComputeBackend) -> ComputeContext:
    """Return a ComputeContext whose available_backends is pre-set."""
    ctx = ComputeContext()
    ctx.available_backends = list(backends)
    return ctx


# ---------------------------------------------------------------------------
# select_backend – CPU_ONLY
# ---------------------------------------------------------------------------


class TestSelectBackendCpuOnly:
    def test_cpu_only_returns_cpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        result = ctx.select_backend(ComputePreference.CPU_ONLY)
        assert result == ComputeBackend.CPU

    def test_cpu_only_ignores_available_gpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)
        result = ctx.select_backend(ComputePreference.CPU_ONLY)
        assert result == ComputeBackend.CPU

    def test_cpu_only_sets_selected_backend(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        ctx.select_backend(ComputePreference.CPU_ONLY)
        assert ctx.selected_backend == ComputeBackend.CPU


# ---------------------------------------------------------------------------
# select_backend – GPU_REQUIRED
# ---------------------------------------------------------------------------


class TestSelectBackendGpuRequired:
    def test_gpu_required_with_cuda_available(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)
        result = ctx.select_backend(ComputePreference.GPU_REQUIRED)
        assert result == ComputeBackend.CUDA

    def test_gpu_required_with_rocm_available(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.ROCM)
        result = ctx.select_backend(ComputePreference.GPU_REQUIRED)
        assert result == ComputeBackend.ROCM

    def test_gpu_required_with_metal_available(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.METAL)
        result = ctx.select_backend(ComputePreference.GPU_REQUIRED)
        assert result == ComputeBackend.METAL

    def test_gpu_required_fails_when_no_gpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        with pytest.raises(RuntimeError, match="GPU_REQUIRED"):
            ctx.select_backend(ComputePreference.GPU_REQUIRED)

    def test_gpu_required_fails_with_empty_backends(self, monkeypatch):
        ctx = _context_with_backends()
        # Prevent auto-detection from finding real hardware
        monkeypatch.setattr(ctx, "detect_hardware", lambda: [ComputeBackend.CPU])

        def fake_detect():
            ctx.available_backends = [ComputeBackend.CPU]
            return ctx.available_backends

        monkeypatch.setattr(ctx, "detect_hardware", fake_detect)
        with pytest.raises(RuntimeError):
            ctx.select_backend(ComputePreference.GPU_REQUIRED)

    def test_gpu_required_sets_selected_backend(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)
        ctx.select_backend(ComputePreference.GPU_REQUIRED)
        assert ctx.selected_backend == ComputeBackend.CUDA

    def test_gpu_required_error_message_lists_available_backends(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        with pytest.raises(RuntimeError) as exc_info:
            ctx.select_backend(ComputePreference.GPU_REQUIRED)
        assert "CPU" in str(exc_info.value)


# ---------------------------------------------------------------------------
# select_backend – GPU_PREFERRED
# ---------------------------------------------------------------------------


class TestSelectBackendGpuPreferred:
    def test_gpu_preferred_uses_gpu_when_available(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)
        result = ctx.select_backend(ComputePreference.GPU_PREFERRED)
        assert result == ComputeBackend.CUDA

    def test_gpu_preferred_falls_back_to_cpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        result = ctx.select_backend(ComputePreference.GPU_PREFERRED)
        assert result == ComputeBackend.CPU

    def test_gpu_preferred_sets_selected_backend_to_gpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.ROCM)
        ctx.select_backend(ComputePreference.GPU_PREFERRED)
        assert ctx.selected_backend == ComputeBackend.ROCM

    def test_gpu_preferred_sets_selected_backend_to_cpu_when_no_gpu(self):
        ctx = _context_with_backends(ComputeBackend.CPU)
        ctx.select_backend(ComputePreference.GPU_PREFERRED)
        assert ctx.selected_backend == ComputeBackend.CPU

    def test_gpu_preferred_with_multiple_gpus_picks_first(self):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA, ComputeBackend.ROCM)
        result = ctx.select_backend(ComputePreference.GPU_PREFERRED)
        # First non-CPU backend in the list should be chosen
        assert result == ComputeBackend.CUDA


# ---------------------------------------------------------------------------
# select_backend – auto-detects hardware when available_backends is empty
# ---------------------------------------------------------------------------


class TestSelectBackendAutoDetect:
    def test_select_backend_triggers_detect_hardware_when_empty(self, monkeypatch):
        ctx = ComputeContext()
        assert ctx.available_backends == []

        detected = [ComputeBackend.CPU]
        monkeypatch.setattr(ctx, "detect_hardware", lambda: detected)

        # Patch available_backends to be set by detect_hardware side-effect
        def fake_detect():
            ctx.available_backends = detected
            return detected

        monkeypatch.setattr(ctx, "detect_hardware", fake_detect)

        result = ctx.select_backend(ComputePreference.CPU_ONLY)
        assert result == ComputeBackend.CPU


# ---------------------------------------------------------------------------
# allocate_device
# ---------------------------------------------------------------------------


class TestAllocateDevice:
    def test_allocate_device_returns_device_dataclass(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU)
        monkeypatch.setattr(ctx, "_get_device_memory", lambda b: 8 * 2**30)

        device = ctx.allocate_device(memory_required=1 * 2**30)
        assert isinstance(device, Device)

    def test_allocate_device_cpu_when_only_cpu(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU)
        monkeypatch.setattr(ctx, "_get_device_memory", lambda b: 8 * 2**30)

        device = ctx.allocate_device(memory_required=1 * 2**30)
        assert device.backend == ComputeBackend.CPU

    def test_allocate_device_prefers_gpu_over_cpu(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)

        def fake_memory(backend):
            return 16 * 2**30 if backend == ComputeBackend.CUDA else 32 * 2**30

        monkeypatch.setattr(ctx, "_get_device_memory", fake_memory)

        device = ctx.allocate_device(memory_required=4 * 2**30)
        assert device.backend == ComputeBackend.CUDA

    def test_allocate_device_falls_back_to_cpu_when_gpu_has_insufficient_memory(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)

        def fake_memory(backend):
            # GPU has only 1 GiB, CPU has plenty
            return 1 * 2**30 if backend == ComputeBackend.CUDA else 32 * 2**30

        monkeypatch.setattr(ctx, "_get_device_memory", fake_memory)

        device = ctx.allocate_device(memory_required=4 * 2**30)
        assert device.backend == ComputeBackend.CPU

    def test_allocate_device_device_index_is_zero(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU)
        monkeypatch.setattr(ctx, "_get_device_memory", lambda b: 8 * 2**30)

        device = ctx.allocate_device(memory_required=0)
        assert device.device_index == 0

    def test_allocate_device_memory_bytes_matches_backend(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU, ComputeBackend.CUDA)
        gpu_mem = 12 * 2**30

        def fake_memory(backend):
            return gpu_mem if backend == ComputeBackend.CUDA else 32 * 2**30

        monkeypatch.setattr(ctx, "_get_device_memory", fake_memory)

        device = ctx.allocate_device(memory_required=1 * 2**30)
        assert device.memory_bytes == gpu_mem

    def test_allocate_device_raises_when_no_device_has_enough_memory(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU)
        monkeypatch.setattr(ctx, "_get_device_memory", lambda b: 0)

        with pytest.raises(RuntimeError):
            ctx.allocate_device(memory_required=1 * 2**30)

    def test_allocate_device_zero_memory_required_always_succeeds(self, monkeypatch):
        ctx = _context_with_backends(ComputeBackend.CPU)
        monkeypatch.setattr(ctx, "_get_device_memory", lambda b: 0)

        # 0 bytes required should always succeed (0 >= 0)
        device = ctx.allocate_device(memory_required=0)
        assert device.backend == ComputeBackend.CPU
