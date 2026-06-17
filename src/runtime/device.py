from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class GPUDeviceBinding:
    requested_gpu: str
    cuda_visible_devices: str
    runtime_device: str


def _list_gpu_indices() -> list[str]:
    try:
        env = os.environ.copy()
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env.pop("CUDA_DEVICE_ORDER", None)
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_cuda_runtime_initialized() -> bool:
    torch = sys.modules.get("torch")
    if torch is None:
        return False
    cuda = getattr(torch, "cuda", None)
    if cuda is None:
        return False
    is_initialized = getattr(cuda, "is_initialized", None)
    if not callable(is_initialized):
        return False
    try:
        return bool(is_initialized())
    except Exception:
        return False


def normalize_gpu_device(gpu_device: str) -> str:
    value = str(gpu_device).strip()
    if not value:
        raise ValueError("gpu_device is required")
    if not value.isdigit():
        raise ValueError(f"gpu_device must be a non-negative integer, got: {gpu_device!r}")
    return value


def activate_gpu_device(gpu_device: str) -> GPUDeviceBinding:
    normalized = normalize_gpu_device(gpu_device)
    available = _list_gpu_indices()
    if available and normalized not in available:
        raise ValueError(f"gpu_device {normalized} is not available; detected GPUs: {', '.join(available)}")

    existing = os.environ.get("CUDA_VISIBLE_DEVICES")
    if existing not in (None, "", normalized) and _is_cuda_runtime_initialized():
        raise ValueError(
            f"CUDA runtime is already bound to GPU {existing}; restart the process before switching to {normalized}"
        )

    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = normalized
    return GPUDeviceBinding(
        requested_gpu=normalized,
        cuda_visible_devices=normalized,
        runtime_device="cuda:0",
    )
