"""Property-based tests for heterogeneous compute detection.

**Validates: Requirements 30.1, 30.2, 30.3, 30.4, 30.5, 30.6, 30.7**

Property 45: Heterogeneous Compute Detection
For any combination of available hardware backends, detect_hardware() must:
1. Always include CPU in the returned backends
2. Only return backends that are actually available (no phantom backends)
3. Return a non-empty list (at minimum CPU)
4. Return a list with no duplicates
5. Return only valid ComputeBackend enum values
"""

from unittest.mock import patch

import pytest
from zerna_contracts.enums import ComputeBackend
from zerna_gpu_abstraction.compute_context import ComputeContext
from hypothesis import given, settings
from hypothesis import strategies as st

# All GPU backends (everything except CPU)
GPU_BACKENDS = [
    ComputeBackend.CUDA,
    ComputeBackend.ROCM,
    ComputeBackend.METAL,
    ComputeBackend.OPENCL,
    ComputeBackend.TPU,
]

# Strategy: generate a subset of GPU backends that are "available"
available_gpu_backends_strategy = st.frozensets(
    st.sampled_from(GPU_BACKENDS),
    min_size=0,
    max_size=len(GPU_BACKENDS),
)


def _make_context_with_available(available_gpu_backends: frozenset) -> list[ComputeBackend]:
    """Run detect_hardware() with mocked individual detectors.

    Each _detect_* method returns True only if its corresponding backend
    is in the available_gpu_backends set.
    """
    context = ComputeContext()

    with (
        patch.object(
            context, "_detect_cuda", return_value=ComputeBackend.CUDA in available_gpu_backends
        ),
        patch.object(
            context, "_detect_rocm", return_value=ComputeBackend.ROCM in available_gpu_backends
        ),
        patch.object(
            context, "_detect_metal", return_value=ComputeBackend.METAL in available_gpu_backends
        ),
        patch.object(
            context, "_detect_opencl", return_value=ComputeBackend.OPENCL in available_gpu_backends
        ),
        patch.object(
            context, "_detect_tpu", return_value=ComputeBackend.TPU in available_gpu_backends
        ),
    ):
        return context.detect_hardware()


@pytest.mark.property
class TestHeterogeneousComputeDetection:
    """Property 45: Heterogeneous Compute Detection.

    **Validates: Requirements 30.1, 30.2, 30.3, 30.4, 30.5, 30.6, 30.7**
    """

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_cpu_always_present(self, available_gpu_backends: frozenset):
        """CPU is always included regardless of which GPU backends are available.

        Validates Req 30.1: detect and utilize all available CPU and GPU resources.
        CPU is always the fallback and must always appear.
        """
        backends = _make_context_with_available(available_gpu_backends)
        assert ComputeBackend.CPU in backends, (
            f"CPU must always be in detected backends, got: {backends}"
        )

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_result_is_non_empty(self, available_gpu_backends: frozenset):
        """detect_hardware() always returns at least one backend (CPU).

        Validates Req 30.1: at minimum CPU is always available.
        """
        backends = _make_context_with_available(available_gpu_backends)
        assert len(backends) >= 1, "detect_hardware() must return at least one backend"

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_no_duplicates(self, available_gpu_backends: frozenset):
        """detect_hardware() never returns duplicate backends.

        Validates Req 30.1: clean enumeration of available resources.
        """
        backends = _make_context_with_available(available_gpu_backends)
        assert len(backends) == len(set(backends)), (
            f"detect_hardware() returned duplicates: {backends}"
        )

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_only_valid_enum_values(self, available_gpu_backends: frozenset):
        """detect_hardware() only returns valid ComputeBackend enum values.

        Validates Req 30.1, 30.2, 30.3, 30.4, 30.5, 30.6: only known backends returned.
        """
        backends = _make_context_with_available(available_gpu_backends)
        valid_backends = set(ComputeBackend)
        for backend in backends:
            assert backend in valid_backends, f"Unknown backend returned: {backend!r}"

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_only_available_backends_returned(self, available_gpu_backends: frozenset):
        """detect_hardware() never returns a GPU backend that is not available.

        Validates Req 30.1: no phantom backends — only actually-available hardware
        is reported.
        """
        backends = _make_context_with_available(available_gpu_backends)
        returned_gpu_backends = {b for b in backends if b != ComputeBackend.CPU}
        phantom = returned_gpu_backends - available_gpu_backends
        assert not phantom, f"Phantom backends returned (not available but detected): {phantom}"

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_all_available_backends_detected(self, available_gpu_backends: frozenset):
        """detect_hardware() includes every backend that is actually available.

        Validates Req 30.2–30.6: CUDA, ROCm, Metal, OpenCL, TPU are each detected
        when present.
        """
        backends = _make_context_with_available(available_gpu_backends)
        returned_set = set(backends)
        for backend in available_gpu_backends:
            assert backend in returned_set, (
                f"Available backend {backend} was not detected. "
                f"Available: {available_gpu_backends}, Detected: {backends}"
            )

    @given(available_gpu_backends_strategy)
    @settings(max_examples=100)
    def test_available_backends_stored_on_context(self, available_gpu_backends: frozenset):
        """detect_hardware() stores results in context.available_backends.

        Validates Req 30.7: the context retains detected backends for use
        when a MethodDefinition is executed.
        """
        context = ComputeContext()
        with (
            patch.object(
                context, "_detect_cuda", return_value=ComputeBackend.CUDA in available_gpu_backends
            ),
            patch.object(
                context, "_detect_rocm", return_value=ComputeBackend.ROCM in available_gpu_backends
            ),
            patch.object(
                context,
                "_detect_metal",
                return_value=ComputeBackend.METAL in available_gpu_backends,
            ),
            patch.object(
                context,
                "_detect_opencl",
                return_value=ComputeBackend.OPENCL in available_gpu_backends,
            ),
            patch.object(
                context, "_detect_tpu", return_value=ComputeBackend.TPU in available_gpu_backends
            ),
        ):
            returned = context.detect_hardware()

        assert context.available_backends == returned, (
            "context.available_backends must equal the return value of detect_hardware()"
        )
