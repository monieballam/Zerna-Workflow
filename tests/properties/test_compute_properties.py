"""Property-based tests for GPU/CPU execution equivalence and fallback.

# Feature: gap-analysis-and-verification, Property 49: GPU/CPU execution equivalence and fallback

**Validates: Requirements 26.2, 26.4**
"""

from unittest.mock import patch

import numpy as np
import pytest
from zerna_contracts.enums import ComputeBackend, ComputePreference
from zerna_gpu_abstraction.compute_context import ComputeContext
from zerna_gpu_abstraction.tensor_ops import CPUTensorOps, TensorOps
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _matrix_st(
    min_dim: int = 2,
    max_dim: int = 20,
) -> st.SearchStrategy[np.ndarray]:
    """Strategy producing random float64 matrices."""
    return (
        st.tuples(
            st.integers(min_value=min_dim, max_value=max_dim),
            st.integers(min_value=min_dim, max_value=max_dim),
        )
        .flatmap(
            lambda shape: st.tuples(
                st.just(shape),
                st.lists(
                    st.floats(
                        min_value=-100.0,
                        max_value=100.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    min_size=shape[0] * shape[1],
                    max_size=shape[0] * shape[1],
                ),
            )
        )
        .map(lambda t: np.array(t[1], dtype=np.float64).reshape(t[0]))
    )


# Strategy for compatible matrix pairs (a @ b must be valid)
_matmul_pair_st = (
    st.tuples(
        st.integers(min_value=2, max_value=15),
        st.integers(min_value=2, max_value=15),
        st.integers(min_value=2, max_value=15),
    )
    .flatmap(
        lambda dims: st.tuples(
            st.just(dims),
            st.lists(
                st.floats(-50.0, 50.0, allow_nan=False, allow_infinity=False),
                min_size=dims[0] * dims[1],
                max_size=dims[0] * dims[1],
            ),
            st.lists(
                st.floats(-50.0, 50.0, allow_nan=False, allow_infinity=False),
                min_size=dims[1] * dims[2],
                max_size=dims[1] * dims[2],
            ),
        )
    )
    .map(
        lambda t: (
            np.array(t[1], dtype=np.float64).reshape(t[0][0], t[0][1]),
            np.array(t[2], dtype=np.float64).reshape(t[0][1], t[0][2]),
        )
    )
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FailingTensorOps(TensorOps):
    """TensorOps that always raises to simulate GPU failure."""

    def matmul(self, a, b):
        raise RuntimeError("Simulated GPU failure")

    def svd(self, a):
        raise RuntimeError("Simulated GPU failure")

    def knn(self, data, k):
        raise RuntimeError("Simulated GPU failure")


def _cpu_only_context() -> ComputeContext:
    """Return a ComputeContext that only has CPU available."""
    ctx = ComputeContext()
    ctx.available_backends = [ComputeBackend.CPU]
    ctx.selected_backend = ComputeBackend.CPU
    return ctx


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestGPUCPUEquivalenceAndFallback:
    """Property 49: For any compute step, the result produced on CPU must be
    numerically equivalent (within tolerance) to the result on GPU. When GPU
    is unavailable, the system must fall back to CPU and produce valid results
    without error.

    **Validates: Requirements 26.2, 26.4**
    """

    # -- CPU-only execution produces valid results --

    @given(pair=_matmul_pair_st)
    @settings(max_examples=100)
    def test_cpu_matmul_produces_valid_result(self, pair: tuple[np.ndarray, np.ndarray]) -> None:
        """CPU matmul produces a finite result matching numpy.

        **Validates: Requirements 26.2**
        """
        a, b = pair
        ops = CPUTensorOps()
        result = ops.matmul(a, b)
        expected = np.matmul(a, b)
        np.testing.assert_allclose(np.asarray(result), expected, rtol=1e-10, atol=1e-12)

    @given(mat=_matrix_st(min_dim=2, max_dim=15))
    @settings(max_examples=100)
    def test_cpu_svd_reconstructs_original(self, mat: np.ndarray) -> None:
        """CPU SVD decomposes and reconstructs the matrix within tolerance.

        **Validates: Requirements 26.2**
        """
        ops = CPUTensorOps()
        U, S, Vh = ops.svd(mat)
        U, S, Vh = np.asarray(U), np.asarray(S), np.asarray(Vh)
        reconstructed = U @ np.diag(S) @ Vh
        np.testing.assert_allclose(reconstructed, mat, rtol=1e-10, atol=1e-10)

    # -- Fallback: GPU unavailable → CPU produces valid results --

    @given(pair=_matmul_pair_st)
    @settings(max_examples=100)
    def test_fallback_to_cpu_when_gpu_unavailable(
        self, pair: tuple[np.ndarray, np.ndarray]
    ) -> None:
        """When no GPU is available, execute_with_fallback uses CPU and
        produces valid results without error.

        **Validates: Requirements 26.4**
        """
        a, b = pair
        ctx = _cpu_only_context()

        def compute(ops: TensorOps, x: np.ndarray, y: np.ndarray) -> np.ndarray:
            return np.asarray(ops.matmul(x, y))

        result, backend_used = ctx.execute_with_fallback(
            compute, a, b, preference=ComputePreference.GPU_PREFERRED
        )
        assert backend_used == ComputeBackend.CPU
        expected = np.matmul(a, b)
        np.testing.assert_allclose(result, expected, rtol=1e-10, atol=1e-12)

    @given(pair=_matmul_pair_st)
    @settings(max_examples=100)
    def test_fallback_on_gpu_runtime_error(self, pair: tuple[np.ndarray, np.ndarray]) -> None:
        """When GPU execution raises at runtime, the system falls back to
        CPU and produces valid results.

        **Validates: Requirements 26.4**
        """
        a, b = pair
        ctx = ComputeContext()
        # Pretend we have a GPU backend
        ctx.available_backends = [ComputeBackend.CPU, ComputeBackend.CUDA]
        ctx.selected_backend = ComputeBackend.CUDA

        call_count = 0

        def compute(ops: TensorOps, x: np.ndarray, y: np.ndarray) -> np.ndarray:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (GPU) fails
                raise RuntimeError("Simulated GPU failure")
            return np.asarray(ops.matmul(x, y))

        # Patch get_tensor_ops to return CPU ops for both calls
        # (since we don't have real CUDA in CI)
        with patch.object(ctx, "get_tensor_ops", return_value=CPUTensorOps()):
            result, backend_used = ctx.execute_with_fallback(
                compute, a, b, preference=ComputePreference.GPU_PREFERRED
            )

        assert backend_used == ComputeBackend.CPU
        expected = np.matmul(a, b)
        np.testing.assert_allclose(result, expected, rtol=1e-10, atol=1e-12)

    # -- select_backend fallback --

    @given(pref=st.sampled_from([ComputePreference.GPU_PREFERRED, ComputePreference.CPU_ONLY]))
    @settings(max_examples=100)
    def test_select_backend_never_errors_without_gpu(self, pref: ComputePreference) -> None:
        """select_backend with GPU_PREFERRED or CPU_ONLY never raises when
        only CPU is available.

        **Validates: Requirements 26.4**
        """
        ctx = _cpu_only_context()
        backend = ctx.select_backend(pref)
        assert backend == ComputeBackend.CPU
