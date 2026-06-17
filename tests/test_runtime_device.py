from __future__ import annotations

import os
import sys
import types

import pytest


def test_activate_gpu_device_sets_runtime_environment(monkeypatch):
    from src.runtime.device import activate_gpu_device

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)
    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0", "1"])

    binding = activate_gpu_device("1")

    assert binding.requested_gpu == "1"
    assert binding.cuda_visible_devices == "1"
    assert binding.runtime_device == "cuda:0"
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "1"
    assert os.environ["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


def test_activate_gpu_device_rejects_unknown_gpu(monkeypatch):
    from src.runtime.device import activate_gpu_device

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0"])

    with pytest.raises(ValueError):
        activate_gpu_device("3")


def test_activate_gpu_device_allows_switch_before_cuda_runtime_init(monkeypatch):
    from src.runtime.device import activate_gpu_device

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0", "1"])

    binding = activate_gpu_device("0")

    assert binding.requested_gpu == "0"
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"


def test_activate_gpu_device_rejects_switch_after_cuda_runtime_init(monkeypatch):
    from src.runtime.device import activate_gpu_device

    class _Cuda:
        @staticmethod
        def is_initialized() -> bool:
            return True

    fake_torch = types.SimpleNamespace(cuda=_Cuda())

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0", "1"])
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    with pytest.raises(ValueError, match="restart the process"):
        activate_gpu_device("0")
