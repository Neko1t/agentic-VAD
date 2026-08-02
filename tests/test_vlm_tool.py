from __future__ import annotations

from pathlib import Path

import torch

from src.core.schemas import TimeSpan, WindowInput
from src.tools import vlm_tool
from src.tools.vlm_tool import VideoLLaMABackend


def test_resolve_time_span_uses_local_timeline_for_temp_video(monkeypatch):
    backend = VideoLLaMABackend(video_root=Path("."))
    temp_video_path = Path("temp_window.mp4")
    backend._video_cache[temp_video_path.as_posix()] = (2.0, 8.0)
    monkeypatch.setattr(vlm_tool, "_TEMP_VIDEO_FILES", {temp_video_path.as_posix()})

    window_input = WindowInput(
        video_id="video_1",
        video_path="video_1.mp4",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=160, end_frame=175),
        frame_indices=list(range(160, 176)),
        frame_paths=["frame_160.jpg", "frame_161.jpg"],
    )

    start_time, end_time = backend._resolve_time_span(temp_video_path, window_input)

    assert start_time == 0.0
    assert end_time == 8.0


def test_resolve_time_span_keeps_original_timeline_for_real_video():
    backend = VideoLLaMABackend(video_root=Path("."))
    real_video_path = Path("video_1.mp4")
    backend._video_cache[real_video_path.as_posix()] = (2.0, 8.0)

    window_input = WindowInput(
        video_id="video_1",
        video_path=str(real_video_path),
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=4, end_frame=7),
        frame_indices=list(range(4, 8)),
    )

    start_time, end_time = backend._resolve_time_span(real_video_path, window_input)

    assert start_time == 2.0
    assert end_time == 3.5


def test_zero_temperature_uses_deterministic_generation(tmp_path, monkeypatch):
    class FakeModel:
        def __init__(self):
            self.generation_kwargs = None

        def parameters(self):
            return iter((torch.zeros(1),))

        def generate(self, **kwargs):
            self.generation_kwargs = kwargs
            return torch.tensor([[1]])

    class FakeProcessor:
        def __call__(self, **_kwargs):
            return {"input_ids": torch.tensor([[1]])}

        def batch_decode(self, _output_ids, skip_special_tokens):
            assert skip_special_tokens is True
            return ["deterministic caption"]

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    model = FakeModel()
    backend = VideoLLaMABackend(video_root=tmp_path, temperature=0.0)
    backend._video_cache[video_path.as_posix()] = (30.0, 10.0)
    monkeypatch.setattr(backend, "_load_model", lambda: (model, FakeProcessor()))

    result = backend.describe(
        WindowInput(
            video_id="video-1",
            video_path=str(video_path),
            window_id="video-1-window-0000",
            time_span=TimeSpan(start_frame=0, end_frame=15, start_time=0.0, end_time=0.5),
            frame_indices=list(range(16)),
        )
    )

    assert result["vision_caption"] == "deterministic caption"
    assert model.generation_kwargs["do_sample"] is False
    assert "temperature" not in model.generation_kwargs
