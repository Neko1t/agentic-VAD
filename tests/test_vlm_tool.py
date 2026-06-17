from __future__ import annotations

from pathlib import Path

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
