"""Unit tests for WorkloadScheduler (task 8.4).

Tests cover:
- GPU_REQUIRED workloads are assigned to GPU devices first
- GPU_PREFERRED workloads fall back to CPU when GPUs are saturated
- Load balancing across multiple GPUs (least-loaded first)
- CPU_ONLY workloads always go to CPU
- Mixed workload batches
- Error cases (no GPU for GPU_REQUIRED, no CPU device)
"""

import pytest
from zerna_contracts.enums import ComputeBackend, ComputePreference
from zerna_gpu_abstraction.compute_context import Device
from zerna_gpu_abstraction.scheduler import (
    MethodWorkload,
    ScheduledWorkload,
    WorkloadScheduler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GiB = 2**30

CPU_DEVICE = (ComputeBackend.CPU, 0, 64 * GiB)
CUDA_0 = (ComputeBackend.CUDA, 0, 16 * GiB)
CUDA_1 = (ComputeBackend.CUDA, 1, 16 * GiB)
ROCM_0 = (ComputeBackend.ROCM, 0, 8 * GiB)


def _wl(
    method_id: str,
    preference: ComputePreference,
    memory_bytes: int = 0,
) -> MethodWorkload:
    return MethodWorkload(
        method_id=method_id,
        compute_preference=preference,
        memory_bytes=memory_bytes,
    )


def _scheduler(*devices: tuple) -> WorkloadScheduler:
    return WorkloadScheduler(list(devices))


# ---------------------------------------------------------------------------
# CPU_ONLY
# ---------------------------------------------------------------------------


class TestCpuOnly:
    def test_cpu_only_assigned_to_cpu(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        results = sched.schedule([_wl("m1", ComputePreference.CPU_ONLY)])
        assert results[0].device.backend == ComputeBackend.CPU

    def test_cpu_only_ignores_available_gpus(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0, ROCM_0)
        results = sched.schedule([_wl("m1", ComputePreference.CPU_ONLY)])
        assert results[0].device.backend == ComputeBackend.CPU

    def test_multiple_cpu_only_all_go_to_cpu(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        workloads = [_wl(f"m{i}", ComputePreference.CPU_ONLY) for i in range(3)]
        results = sched.schedule(workloads)
        assert all(r.device.backend == ComputeBackend.CPU for r in results)


# ---------------------------------------------------------------------------
# GPU_REQUIRED
# ---------------------------------------------------------------------------


class TestGpuRequired:
    def test_gpu_required_assigned_to_gpu(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        results = sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED)])
        assert results[0].device.backend == ComputeBackend.CUDA

    def test_gpu_required_raises_when_no_gpu_available(self):
        sched = _scheduler(CPU_DEVICE)
        with pytest.raises(RuntimeError, match="GPU_REQUIRED"):
            sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED)])

    def test_gpu_required_raises_when_gpu_memory_insufficient(self):
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 4 * GiB))
        with pytest.raises(RuntimeError):
            sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED, 8 * GiB)])

    def test_gpu_required_does_not_fall_back_to_cpu(self):
        sched = _scheduler(CPU_DEVICE)
        with pytest.raises(RuntimeError):
            sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED)])

    def test_gpu_required_uses_rocm_when_only_rocm_available(self):
        sched = _scheduler(CPU_DEVICE, ROCM_0)
        results = sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED)])
        assert results[0].device.backend == ComputeBackend.ROCM


# ---------------------------------------------------------------------------
# GPU_PREFERRED
# ---------------------------------------------------------------------------


class TestGpuPreferred:
    def test_gpu_preferred_uses_gpu_when_available(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        results = sched.schedule([_wl("m1", ComputePreference.GPU_PREFERRED)])
        assert results[0].device.backend == ComputeBackend.CUDA

    def test_gpu_preferred_falls_back_to_cpu_when_no_gpu(self):
        sched = _scheduler(CPU_DEVICE)
        results = sched.schedule([_wl("m1", ComputePreference.GPU_PREFERRED)])
        assert results[0].device.backend == ComputeBackend.CPU

    def test_gpu_preferred_falls_back_to_cpu_when_gpu_memory_full(self):
        # GPU has only 2 GiB free, workload needs 4 GiB
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 2 * GiB))
        results = sched.schedule([_wl("m1", ComputePreference.GPU_PREFERRED, 4 * GiB)])
        assert results[0].device.backend == ComputeBackend.CPU


# ---------------------------------------------------------------------------
# Load balancing across multiple GPUs
# ---------------------------------------------------------------------------


class TestLoadBalancing:
    def test_two_workloads_spread_across_two_gpus(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0, CUDA_1)
        workloads = [
            _wl("m1", ComputePreference.GPU_REQUIRED, 4 * GiB),
            _wl("m2", ComputePreference.GPU_REQUIRED, 4 * GiB),
        ]
        results = sched.schedule(workloads)
        backends = [r.device.backend for r in results]
        indices = [r.device.device_index for r in results]
        # Both should be on CUDA
        assert all(b == ComputeBackend.CUDA for b in backends)
        # They should be on different device indices (load balanced)
        assert indices[0] != indices[1]

    def test_least_loaded_gpu_chosen_first(self):
        # GPU 0 has 16 GiB, GPU 1 has 8 GiB → GPU 0 should be chosen first
        sched = _scheduler(
            CPU_DEVICE,
            (ComputeBackend.CUDA, 0, 16 * GiB),
            (ComputeBackend.CUDA, 1, 8 * GiB),
        )
        results = sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED, 4 * GiB)])
        assert results[0].device.device_index == 0

    def test_heterogeneous_gpus_load_balanced(self):
        # CUDA 16 GiB, ROCm 8 GiB → first workload goes to CUDA (more free memory)
        sched = _scheduler(CPU_DEVICE, CUDA_0, ROCM_0)
        results = sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED, 4 * GiB)])
        assert results[0].device.backend == ComputeBackend.CUDA

    def test_memory_accounting_across_assignments(self):
        # GPU has 8 GiB; two 4 GiB workloads should both fit
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 8 * GiB))
        workloads = [
            _wl("m1", ComputePreference.GPU_REQUIRED, 4 * GiB),
            _wl("m2", ComputePreference.GPU_REQUIRED, 4 * GiB),
        ]
        results = sched.schedule(workloads)
        assert all(r.device.backend == ComputeBackend.CUDA for r in results)

    def test_third_workload_overflows_to_cpu_when_gpus_full(self):
        # GPU has 8 GiB; two 4 GiB GPU_REQUIRED workloads fill it,
        # a GPU_PREFERRED workload should fall back to CPU
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 8 * GiB))
        workloads = [
            _wl("m1", ComputePreference.GPU_REQUIRED, 4 * GiB),
            _wl("m2", ComputePreference.GPU_REQUIRED, 4 * GiB),
            _wl("m3", ComputePreference.GPU_PREFERRED, 4 * GiB),
        ]
        results = sched.schedule(workloads)
        assert results[0].device.backend == ComputeBackend.CUDA
        assert results[1].device.backend == ComputeBackend.CUDA
        assert results[2].device.backend == ComputeBackend.CPU


# ---------------------------------------------------------------------------
# GPU_REQUIRED gets priority over GPU_PREFERRED
# ---------------------------------------------------------------------------


class TestGpuRequiredPriority:
    def test_gpu_required_claims_gpu_before_gpu_preferred(self):
        # GPU has exactly 4 GiB; GPU_REQUIRED needs 4 GiB (fills it completely).
        # GPU_PREFERRED also needs 4 GiB but must fall back to CPU because
        # GPU_REQUIRED is processed first and exhausts the GPU.
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 4 * GiB))
        workloads = [
            # GPU_PREFERRED listed first in input order
            _wl("preferred", ComputePreference.GPU_PREFERRED, 4 * GiB),
            _wl("required", ComputePreference.GPU_REQUIRED, 4 * GiB),
        ]
        results = sched.schedule(workloads)
        by_id = {r.workload.method_id: r for r in results}
        # GPU_REQUIRED must be on GPU
        assert by_id["required"].device.backend == ComputeBackend.CUDA
        # GPU_PREFERRED must fall back to CPU because GPU is now full
        assert by_id["preferred"].device.backend == ComputeBackend.CPU

    def test_multiple_gpu_required_all_get_gpus_when_capacity_allows(self):
        sched = _scheduler(
            CPU_DEVICE,
            (ComputeBackend.CUDA, 0, 16 * GiB),
            (ComputeBackend.CUDA, 1, 16 * GiB),
        )
        workloads = [_wl(f"req{i}", ComputePreference.GPU_REQUIRED, 4 * GiB) for i in range(4)]
        results = sched.schedule(workloads)
        assert all(r.device.backend == ComputeBackend.CUDA for r in results)


# ---------------------------------------------------------------------------
# Mixed workloads
# ---------------------------------------------------------------------------


class TestMixedWorkloads:
    def test_mixed_preferences_correct_assignment(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        workloads = [
            _wl("cpu_wl", ComputePreference.CPU_ONLY),
            _wl("gpu_req", ComputePreference.GPU_REQUIRED),
            _wl("gpu_pref", ComputePreference.GPU_PREFERRED),
        ]
        results = sched.schedule(workloads)
        by_id = {r.workload.method_id: r for r in results}
        assert by_id["cpu_wl"].device.backend == ComputeBackend.CPU
        assert by_id["gpu_req"].device.backend == ComputeBackend.CUDA
        # GPU_PREFERRED may be on GPU or CPU depending on remaining memory
        assert by_id["gpu_pref"].device.backend in (ComputeBackend.CUDA, ComputeBackend.CPU)

    def test_output_order_matches_input_order(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        workloads = [
            _wl("a", ComputePreference.CPU_ONLY),
            _wl("b", ComputePreference.GPU_REQUIRED),
            _wl("c", ComputePreference.GPU_PREFERRED),
        ]
        results = sched.schedule(workloads)
        assert [r.workload.method_id for r in results] == ["a", "b", "c"]

    def test_empty_workload_list_returns_empty(self):
        sched = _scheduler(CPU_DEVICE, CUDA_0)
        results = sched.schedule([])
        assert results == []

    def test_returns_scheduled_workload_instances(self):
        sched = _scheduler(CPU_DEVICE)
        results = sched.schedule([_wl("m1", ComputePreference.CPU_ONLY)])
        assert isinstance(results[0], ScheduledWorkload)
        assert isinstance(results[0].device, Device)
        assert isinstance(results[0].workload, MethodWorkload)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_memory_workload_always_fits(self):
        sched = _scheduler(CPU_DEVICE, (ComputeBackend.CUDA, 0, 0))
        results = sched.schedule([_wl("m1", ComputePreference.GPU_REQUIRED, 0)])
        assert results[0].device.backend == ComputeBackend.CUDA

    def test_no_cpu_device_raises_for_cpu_only(self):
        sched = _scheduler(CUDA_0)
        with pytest.raises(RuntimeError):
            sched.schedule([_wl("m1", ComputePreference.CPU_ONLY)])

    def test_no_cpu_device_raises_for_gpu_preferred_fallback(self):
        # GPU has 0 memory, GPU_PREFERRED must fall back to CPU, but no CPU registered
        sched = _scheduler((ComputeBackend.CUDA, 0, 0))
        with pytest.raises(RuntimeError):
            sched.schedule([_wl("m1", ComputePreference.GPU_PREFERRED, 4 * GiB)])
