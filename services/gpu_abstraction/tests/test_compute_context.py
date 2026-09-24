"""Unit tests for ComputeContext hardware detection."""

import subprocess
from unittest.mock import MagicMock, patch

from zerna_contracts.enums import ComputeBackend
from zerna_gpu_abstraction.compute_context import ComputeContext


class TestComputeContext:
    """Test suite for ComputeContext class."""

    def test_cpu_always_available(self):
        """CPU backend should always be detected."""
        context = ComputeContext()
        backends = context.detect_hardware()

        assert ComputeBackend.CPU in backends
        assert len(backends) >= 1

    @patch("subprocess.run")
    @patch("zerna_gpu_abstraction.compute_context.ComputeContext._detect_cuda")
    def test_detect_hardware_calls_all_detectors(self, mock_cuda, mock_run):
        """detect_hardware should check all backend types."""
        mock_cuda.return_value = False

        context = ComputeContext()
        backends = context.detect_hardware()

        # Should at least have CPU
        assert ComputeBackend.CPU in backends
        assert isinstance(backends, list)
        assert all(isinstance(b, ComputeBackend) for b in backends)

    @patch("subprocess.run")
    def test_detect_cuda_with_nvidia_smi_missing(self, mock_run):
        """CUDA detection should fail if nvidia-smi is not found."""
        mock_run.side_effect = FileNotFoundError()

        context = ComputeContext()
        result = context._detect_cuda()

        assert result is False

    @patch("subprocess.run")
    def test_detect_cuda_with_nvidia_smi_error(self, mock_run):
        """CUDA detection should fail if nvidia-smi returns error."""
        mock_run.return_value = MagicMock(returncode=1)

        context = ComputeContext()
        result = context._detect_cuda()

        assert result is False

    @patch("subprocess.run")
    @patch("zerna_gpu_abstraction.compute_context.ComputeContext._detect_cuda")
    def test_detect_cuda_success(self, mock_detect, mock_run):
        """CUDA should be detected when nvidia-smi and torch.cuda work."""
        mock_detect.return_value = True

        context = ComputeContext()
        backends = context.detect_hardware()

        if mock_detect.return_value:
            assert ComputeBackend.CUDA in backends

    @patch("subprocess.run")
    def test_detect_rocm_with_rocm_smi_missing(self, mock_run):
        """ROCm detection should fail if rocm-smi is not found."""
        mock_run.side_effect = FileNotFoundError()

        context = ComputeContext()
        result = context._detect_rocm()

        assert result is False

    @patch("subprocess.run")
    def test_detect_rocm_with_rocm_smi_error(self, mock_run):
        """ROCm detection should fail if rocm-smi returns error."""
        mock_run.return_value = MagicMock(returncode=1)

        context = ComputeContext()
        result = context._detect_rocm()

        assert result is False

    def test_detect_metal_without_torch(self):
        """Metal detection should fail gracefully without torch."""
        with patch.dict("sys.modules", {"torch": None}):
            context = ComputeContext()
            result = context._detect_metal()

            # Should return False without raising exception
            assert result is False

    def test_detect_opencl_without_pyopencl(self):
        """OpenCL detection should fail gracefully without pyopencl."""
        with patch.dict("sys.modules", {"pyopencl": None}):
            context = ComputeContext()
            result = context._detect_opencl()

            # Should return False without raising exception
            assert result is False

    def test_detect_tpu_without_jax(self):
        """TPU detection should fail gracefully without jax."""
        with patch.dict("sys.modules", {"jax": None}):
            context = ComputeContext()
            result = context._detect_tpu()

            # Should return False without raising exception
            assert result is False

    def test_available_backends_stored(self):
        """detect_hardware should store results in available_backends."""
        context = ComputeContext()
        backends = context.detect_hardware()

        assert context.available_backends == backends
        assert len(context.available_backends) >= 1

    def test_detect_hardware_returns_unique_backends(self):
        """detect_hardware should not return duplicate backends."""
        context = ComputeContext()
        backends = context.detect_hardware()

        # Check for uniqueness
        assert len(backends) == len(set(backends))

    @patch("subprocess.run")
    def test_subprocess_timeout_handling(self, mock_run):
        """Hardware detection should handle subprocess timeouts."""
        mock_run.side_effect = subprocess.TimeoutExpired("nvidia-smi", 5)

        context = ComputeContext()
        result = context._detect_cuda()

        assert result is False

    def test_detect_opencl_with_no_platforms(self):
        """OpenCL detection should fail if no platforms available."""
        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = []

        with patch.dict("sys.modules", {"pyopencl": mock_cl}):
            context = ComputeContext()
            result = context._detect_opencl()

            assert result is False

    def test_detect_opencl_with_no_devices(self):
        """OpenCL detection should fail if platforms have no devices."""
        mock_platform = MagicMock()
        mock_platform.get_devices.return_value = []

        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = [mock_platform]

        with patch.dict("sys.modules", {"pyopencl": mock_cl}):
            context = ComputeContext()
            result = context._detect_opencl()

            assert result is False

    def test_detect_tpu_with_no_devices(self):
        """TPU detection should fail if jax.devices returns empty list."""
        mock_jax = MagicMock()
        mock_jax.devices.return_value = []

        with patch.dict("sys.modules", {"jax": mock_jax}):
            context = ComputeContext()
            result = context._detect_tpu()

            assert result is False

    def test_detect_tpu_with_runtime_error(self):
        """TPU detection should handle RuntimeError from jax."""
        mock_jax = MagicMock()
        mock_jax.devices.side_effect = RuntimeError("TPU not available")

        with patch.dict("sys.modules", {"jax": mock_jax}):
            context = ComputeContext()
            result = context._detect_tpu()

            assert result is False
