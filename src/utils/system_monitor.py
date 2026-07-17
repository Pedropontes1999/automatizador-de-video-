"""Monitor de recursos do sistema para o Dashboard (CPU, RAM, GPU)."""
from __future__ import annotations

from dataclasses import dataclass

import psutil

# pynvml é opcional: sem GPU NVIDIA o dashboard mostra apenas CPU/RAM.
try:
    import pynvml

    pynvml.nvmlInit()
    _NVML_OK = True
except Exception:  # noqa: BLE001 - qualquer falha desativa o suporte a GPU
    _NVML_OK = False


@dataclass(frozen=True)
class SystemStats:
    """Fotografia instantânea do uso de recursos."""

    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    gpu_percent: float | None  # None = GPU indisponível
    gpu_mem_percent: float | None


def get_stats() -> SystemStats:
    """Coleta uso atual de CPU, RAM e GPU (se disponível)."""
    mem = psutil.virtual_memory()
    gpu_percent: float | None = None
    gpu_mem: float | None = None
    if _NVML_OK:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            meminfo = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_percent = float(util.gpu)
            gpu_mem = meminfo.used / meminfo.total * 100.0
        except Exception:  # noqa: BLE001
            pass
    return SystemStats(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_percent=mem.percent,
        ram_used_gb=mem.used / 1024**3,
        ram_total_gb=mem.total / 1024**3,
        gpu_percent=gpu_percent,
        gpu_mem_percent=gpu_mem,
    )
