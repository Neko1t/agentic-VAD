import json

from src.core.schemas import TimeSpan, WindowInput
from src.tools.vlm_tool import MockVLMBackend, VLMTool


def _window(start_frame: int = 0, end_frame: int = 15) -> WindowInput:
    return WindowInput(
        video_id="video_1",
        video_path="video_1.mp4",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=start_frame, end_frame=end_frame),
        frame_indices=list(range(start_frame, end_frame + 1)),
    )


def test_vlm_tool_reads_precomputed_caption_backend(tmp_path):
    caption_file = tmp_path / "video_1.json"
    caption_file.write_text(
        json.dumps(
            {
                "0": "A person is walking on a street.",
                "10": "The person starts running.",
            }
        ),
        encoding="utf-8",
    )

    result = VLMTool(captions_dir=tmp_path).vlm_describe(_window())

    assert "walking" in result["vision_caption"]
    assert "running" in result["vision_caption"]
    assert result["backend_name"] == "precomputed_caption"
    assert result["artifact_refs"] == [str(caption_file)]
    assert "run" in result["actions"]
    assert result["scene_context"] == "outdoor street scene"


def test_vlm_tool_uses_mock_backend_for_deterministic_tests():
    tool = VLMTool(backend=MockVLMBackend(caption="A man grabs a bag in a store."))

    result = tool.vlm_describe(_window())

    assert result["backend_name"] == "mock_vlm"
    assert result["confidence"] == 1.0
    assert "grab" in result["actions"]
    assert "man" in result["entities"]
    assert result["scene_context"] == "commercial indoor scene"
