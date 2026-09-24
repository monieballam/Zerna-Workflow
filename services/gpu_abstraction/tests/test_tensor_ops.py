"""Unit tests for TensorOps implementations."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from zerna_gpu_abstraction.tensor_ops import (
    CPUTensorOps,
    CUDATensorOps,
    MetalTensorOps,
    OpenCLTensorOps,
    ROCmTensorOps,
    TensorOps,
    TPUTensorOps,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_matrix(rows: int, cols: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((rows, cols)).astype(np.float32)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class TestTensorOpsInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            TensorOps()  # type: ignore[abstract]

    def test_cpu_is_concrete(self):
        ops = CPUTensorOps()
        assert isinstance(ops, TensorOps)


# ---------------------------------------------------------------------------
# CPUTensorOps
# ---------------------------------------------------------------------------


class TestCPUTensorOps:
    def setup_method(self):
        self.ops = CPUTensorOps()

    def test_matmul_shape(self):
        a = _make_matrix(3, 4)
        b = _make_matrix(4, 5)
        result = self.ops.matmul(a, b)
        assert result.shape == (3, 5)

    def test_matmul_correctness(self):
        a = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        b = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
        result = self.ops.matmul(a, b)
        expected = np.matmul(a, b)
        np.testing.assert_allclose(result, expected, rtol=1e-5)

    def test_svd_shapes(self):
        a = _make_matrix(6, 4)
        U, S, Vh = self.ops.svd(a)
        assert U.shape == (6, 4)
        assert S.shape == (4,)
        assert Vh.shape == (4, 4)

    def test_svd_reconstruction(self):
        a = _make_matrix(5, 3)
        U, S, Vh = self.ops.svd(a)
        reconstructed = U @ np.diag(S) @ Vh
        np.testing.assert_allclose(reconstructed, a, atol=1e-5)

    def test_svd_singular_values_non_negative(self):
        a = _make_matrix(8, 6)
        _, S, _ = self.ops.svd(a)
        assert np.all(S >= 0)

    def test_svd_singular_values_descending(self):
        a = _make_matrix(8, 6)
        _, S, _ = self.ops.svd(a)
        assert np.all(S[:-1] >= S[1:])

    def test_knn_shape(self):
        data = _make_matrix(10, 4)
        indices = self.ops.knn(data, k=3)
        assert indices.shape == (10, 3)

    def test_knn_no_self_reference(self):
        data = _make_matrix(10, 4)
        indices = self.ops.knn(data, k=3)
        for i, row in enumerate(indices):
            assert i not in row, f"Point {i} appears in its own neighbours"

    def test_knn_indices_in_range(self):
        n = 10
        data = _make_matrix(n, 4)
        indices = self.ops.knn(data, k=4)
        assert np.all(indices >= 0)
        assert np.all(indices < n)

    def test_knn_k_equals_n_minus_1(self):
        n = 5
        data = _make_matrix(n, 3)
        indices = self.ops.knn(data, k=n - 1)
        assert indices.shape == (n, n - 1)

    def test_matmul_accepts_list_input(self):
        a = [[1.0, 0.0], [0.0, 1.0]]
        b = [[2.0, 3.0], [4.0, 5.0]]
        result = self.ops.matmul(a, b)
        np.testing.assert_allclose(result, np.array(b, dtype=float))

    def test_svd_square_matrix(self):
        a = _make_matrix(4, 4)
        U, S, Vh = self.ops.svd(a)
        assert U.shape == (4, 4)
        assert S.shape == (4,)
        assert Vh.shape == (4, 4)


# ---------------------------------------------------------------------------
# GPU backends – unavailable library handling
# ---------------------------------------------------------------------------


class TestCUDATensorOpsUnavailable:
    def test_raises_import_error_when_no_cuda(self):
        with patch.dict("sys.modules", {"cupy": None, "torch": None}):
            with pytest.raises(ImportError, match="CUDATensorOps"):
                CUDATensorOps()

    def test_raises_import_error_when_torch_no_cuda(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict("sys.modules", {"cupy": None, "torch": mock_torch}):
            with pytest.raises(ImportError):
                CUDATensorOps()


class TestROCmTensorOpsUnavailable:
    def test_raises_import_error_when_no_torch(self):
        with patch.dict("sys.modules", {"torch": None}):
            with pytest.raises(ImportError, match="ROCmTensorOps"):
                ROCmTensorOps()

    def test_raises_import_error_when_hip_unavailable(self):
        mock_torch = MagicMock()
        mock_torch.hip.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}), pytest.raises(ImportError):
            ROCmTensorOps()


class TestMetalTensorOpsUnavailable:
    def test_raises_import_error_when_no_torch(self):
        with patch.dict("sys.modules", {"torch": None}):
            with pytest.raises(ImportError, match="MetalTensorOps"):
                MetalTensorOps()

    def test_raises_import_error_when_mps_unavailable(self):
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}), pytest.raises(ImportError):
            MetalTensorOps()


class TestOpenCLTensorOpsUnavailable:
    def test_raises_import_error_when_no_pyopencl(self):
        with patch.dict("sys.modules", {"pyopencl": None, "pyopencl.array": None}):
            with pytest.raises(ImportError, match="OpenCLTensorOps"):
                OpenCLTensorOps()

    def test_raises_import_error_when_no_platforms(self):
        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = []
        with patch.dict("sys.modules", {"pyopencl": mock_cl, "pyopencl.array": MagicMock()}):
            with pytest.raises(ImportError):
                OpenCLTensorOps()

    def test_raises_import_error_when_no_devices(self):
        mock_platform = MagicMock()
        mock_platform.get_devices.return_value = []
        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = [mock_platform]
        with patch.dict("sys.modules", {"pyopencl": mock_cl, "pyopencl.array": MagicMock()}):
            with pytest.raises(ImportError):
                OpenCLTensorOps()


class TestTPUTensorOpsUnavailable:
    def test_raises_import_error_when_no_jax(self):
        with patch.dict("sys.modules", {"jax": None, "jax.numpy": None}):
            with pytest.raises(ImportError, match="TPUTensorOps"):
                TPUTensorOps()

    def test_raises_import_error_when_no_tpu_devices(self):
        mock_jax = MagicMock()
        mock_jax.devices.return_value = []
        with patch.dict("sys.modules", {"jax": mock_jax, "jax.numpy": MagicMock()}):
            with pytest.raises(ImportError):
                TPUTensorOps()

    def test_raises_import_error_on_runtime_error(self):
        mock_jax = MagicMock()
        mock_jax.devices.side_effect = RuntimeError("TPU not available")
        with patch.dict("sys.modules", {"jax": mock_jax, "jax.numpy": MagicMock()}):
            with pytest.raises(ImportError):
                TPUTensorOps()
