from src.agents.perception_agent import PerceptionAgent
from src.core.config import ScoringConfig
from src.core.schemas import TimeSpan, WindowInput
from src.tools.audio_tool import AudioTool
from src.tools.ocr_tool import OCRTool
from src.tools.score_tool import ScoreTool
from src.tools.vlm_tool import MockVLMBackend, VLMTool


class FailingVLMBackend:
    name = "failing_vlm"

    def describe(self, window_input):
        raise RuntimeError("vlm unavailable")


def test_perception_agent_returns_observation_with_tool_trace():
    agent = PerceptionAgent(
        vlm_tool=VLMTool(backend=MockVLMBackend(caption="A person runs and falls on a street.")),
        audio_tool=AudioTool(enabled=False),
        ocr_tool=OCRTool(enabled=False),
        score_tool=ScoreTool(ScoringConfig()),
    )
    window = WindowInput(
        video_id="video_1",
        video_path="video_1.mp4",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
        frame_indices=list(range(16)),
    )

    card = agent.process_window(window)

    assert card.vision_caption == "A person runs and falls on a street."
    assert "run" in card.actions
    assert "fall" in card.actions
    assert card.score_weighted >= 8.0
    assert [record.tool_name for record in card.tool_trace] == [
        "vlm_describe",
        "audio_describe",
        "ocr_extract",
        "score_observation",
    ]
    assert card.tool_trace[0].confidence == 1.0
    assert "weighted=" in card.tool_trace[-1].output_summary
    assert all(record.latency_ms is not None for record in card.tool_trace)
    assert all(record.latency_ms >= 0.0 for record in card.tool_trace)
    assert all(record.error is None for record in card.tool_trace)


def test_perception_agent_records_tool_error_and_uses_fallback():
    agent = PerceptionAgent(
        vlm_tool=VLMTool(backend=FailingVLMBackend()),
        audio_tool=AudioTool(enabled=False),
        ocr_tool=OCRTool(enabled=False),
        score_tool=ScoreTool(ScoringConfig()),
    )
    window = WindowInput(
        video_id="video_1",
        video_path="video_1.mp4",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
        frame_indices=list(range(16)),
    )

    card = agent.process_window(window)

    assert card.vision_caption == ""
    assert card.modality_confidence.vision_conf == 0.0
    assert card.tool_trace[0].tool_name == "vlm_describe"
    assert "RuntimeError" in card.tool_trace[0].error
    assert card.tool_trace[0].latency_ms is not None
    assert card.score_weighted == 3.5
