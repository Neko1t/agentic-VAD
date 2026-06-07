from src.core.schemas import (
    CalibrationResult,
    EpisodeSummary,
    MemoryWriteDecision,
    MemoryWriteEvent,
    ModalityConfidence,
    ObservationCard,
    RetrievalResult,
    RollingSummaryState,
    RunMode,
    StoryMemoryInput,
    StoryMemoryResult,
    TimeSpan,
    ToolCallRecord,
)


def test_observation_card_defaults():
    card = ObservationCard(
        video_id="video_1",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
    )
    assert card.score_weighted == 0.0
    assert card.modality_confidence == ModalityConfidence()
    assert card.entities == []
    assert card.tool_trace == []


def test_agent_communication_schema_defaults():
    tool_call = ToolCallRecord(tool_name="vlm_describe")
    assert tool_call.artifact_refs == []
    assert tool_call.confidence is None

    state = RollingSummaryState(video_id="video_1")
    observation = ObservationCard(
        video_id="video_1",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
    )
    story_input = StoryMemoryInput(
        video_id="video_1",
        state=state,
        recent_observations=[observation],
    )
    assert story_input.run_mode == RunMode.ONLINE_INFERENCE
    assert story_input.top_k == 5

    episode = EpisodeSummary(
        video_id="video_1",
        segment_span=TimeSpan(start_frame=0, end_frame=15),
        story_text="A normal scene.",
        action_sequence="walk",
    )
    calibration = CalibrationResult(
        score_local=2.0,
        score_story=2.0,
        score_memory_adjusted=2.0,
        final_score=2.0,
    )
    event = MemoryWriteEvent(
        decision=MemoryWriteDecision.SKIP,
        reason="low value",
        skip_codes=["low_information_value"],
    )
    result = StoryMemoryResult(
        video_id="video_1",
        episode=episode,
        state=state,
        retrieval=RetrievalResult(),
        calibration=calibration,
        memory_event=event,
    )
    assert result.memory_event.decision == MemoryWriteDecision.SKIP
    assert result.tool_trace == []
    assert result.contradiction_flags == []
