"""WorkloadScheduler for distributing method workloads across heterogeneous hardware.

Implements workload distribution per Requirement 30.9:
- Prioritizes GPU-required methods for GPU resources
- Balances load across multiple GPUs of different types
- Falls back to CPU for GPU-preferred methods when GPUs are saturated
"""

from __future__ import annotations

from dataclasses import dataclass

from zerna_contracts.enums import ComputeBackend, ComputePreference
from zerna_gpu_abstraction.compute_context import Device


@dataclass
class MethodWorkload:
    """Represents a single method workload to be scheduled.

    Attributes:
        method_id: Unique identifier for the method instance.
        compute_preference: CPU_ONLY, GPU_PREFERRED, or GPU_REQUIRED.
        memory_bytes: Estimated memory requirement in bytes.
    """

    method_id: str
    compute_preference: ComputePreference
    memory_bytes: int = 0


@dataclass
class ScheduledWorkload:
    """A method workload paired with its assigned device.

    Attributes:
        workload: The original MethodWorkload.
        device: The Device assigned to this workload.
    """

    workload: MethodWorkload
    device: Device


@dataclass
class _DeviceSlot:
    """Internal tracking of a device and its remaining free memory."""

    backend: ComputeBackend
    device_index: int
    total_memory: int
    free_memory: int

    def can_fit(self, memory_bytes: int) -> bool:
        return self.free_memory >= memory_bytes

    def allocate(self, memory_bytes: int) -> None:
        self.free_memory -= memory_bytes

    def to_device(self) -> Device:
        return Device(
            backend=self.backend,
            device_index=self.device_index,
            memory_bytes=self.free_memory,
        )


class WorkloadScheduler:
    """Distributes method workloads across available compute backends.

    Scheduling policy (in priority order):
    1. GPU_REQUIRED workloads are assigned to GPU devices first.
       If no GPU has sufficient free memory, a RuntimeError is raised.
    2. GPU_PREFERRED workloads are assigned to the least-loaded GPU
       (most free memory) that can fit the workload.  If no GPU can
       accommodate the workload, it falls back to CPU.
    3. CPU_ONLY workloads are always assigned to the CPU device.

    Load balancing across multiple GPUs is achieved by always picking
    the GPU with the most remaining free memory (least-loaded first).

    Args:
        available_devices: List of (backend, device_index, memory_bytes) tuples
            describing the available compute devices.  Typically obtained from
            :meth:`ComputeContext.detect_hardware` combined with per-device
            memory queries.  At minimum a CPU entry should be present.
    """

    def __init__(
        self,
        available_devices: list[tuple[ComputeBackend, int, int]],
    ) -> None:
        self._slots: list[_DeviceSlot] = [
            _DeviceSlot(
                backend=backend,
                device_index=idx,
                total_memory=mem,
                free_memory=mem,
            )
            for backend, idx, mem in available_devices
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def schedule(self, workloads: list[MethodWorkload]) -> list[ScheduledWorkload]:
        """Distribute workloads across available devices.

        GPU_REQUIRED workloads are processed first to ensure they claim
        GPU resources before GPU_PREFERRED workloads compete for them.

        Args:
            workloads: List of method workloads to schedule.

        Returns:
            List of ScheduledWorkload in the same order as the input.

        Raises:
            RuntimeError: If a GPU_REQUIRED workload cannot be assigned
                to any GPU device (no GPU available or insufficient memory).
        """
        # Build an index so we can return results in original order
        assignments: dict[str, Device] = {}

        # Phase 1: assign GPU_REQUIRED workloads first
        for wl in workloads:
            if wl.compute_preference == ComputePreference.GPU_REQUIRED:
                device = self._assign_gpu(wl, required=True)
                assignments[wl.method_id] = device

        # Phase 2: assign GPU_PREFERRED workloads
        for wl in workloads:
            if wl.compute_preference == ComputePreference.GPU_PREFERRED:
                device = self._assign_gpu_or_cpu(wl)
                assignments[wl.method_id] = device

        # Phase 3: assign CPU_ONLY workloads
        for wl in workloads:
            if wl.compute_preference == ComputePreference.CPU_ONLY:
                device = self._assign_cpu(wl)
                assignments[wl.method_id] = device

        return [
            ScheduledWorkload(workload=wl, device=assignments[wl.method_id]) for wl in workloads
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gpu_slots(self) -> list[_DeviceSlot]:
        """Return GPU slots sorted by free memory descending (least loaded first)."""
        return sorted(
            [s for s in self._slots if s.backend != ComputeBackend.CPU],
            key=lambda s: s.free_memory,
            reverse=True,
        )

    def _cpu_slot(self) -> _DeviceSlot | None:
        for s in self._slots:
            if s.backend == ComputeBackend.CPU:
                return s
        return None

    def _assign_gpu(self, wl: MethodWorkload, *, required: bool) -> Device:
        """Assign workload to the least-loaded GPU that can fit it.

        Args:
            wl: The workload to assign.
            required: If True, raise RuntimeError when no GPU is available.

        Returns:
            The assigned Device.

        Raises:
            RuntimeError: When required=True and no GPU can accommodate the workload.
        """
        for slot in self._gpu_slots():
            if slot.can_fit(wl.memory_bytes):
                slot.allocate(wl.memory_bytes)
                return slot.to_device()

        if required:
            gpu_slots = self._gpu_slots()
            if not gpu_slots:
                raise RuntimeError(
                    f"GPU_REQUIRED workload '{wl.method_id}' cannot be scheduled: "
                    "no GPU devices are available."
                )
            raise RuntimeError(
                f"GPU_REQUIRED workload '{wl.method_id}' cannot be scheduled: "
                f"no GPU device has sufficient free memory "
                f"(required {wl.memory_bytes} bytes)."
            )
        # Not required – signal caller to fall back
        raise _NoGpuAvailable()

    def _assign_gpu_or_cpu(self, wl: MethodWorkload) -> Device:
        """Assign GPU_PREFERRED workload to GPU if possible, else CPU."""
        try:
            return self._assign_gpu(wl, required=False)
        except _NoGpuAvailable:
            return self._assign_cpu(wl)

    def _assign_cpu(self, wl: MethodWorkload) -> Device:
        """Assign workload to the CPU device."""
        slot = self._cpu_slot()
        if slot is None:
            raise RuntimeError(
                f"Cannot schedule workload '{wl.method_id}': no CPU device registered."
            )
        slot.allocate(wl.memory_bytes)
        return slot.to_device()


class _NoGpuAvailable(Exception):
    """Internal sentinel raised when no GPU slot can fit a workload."""
