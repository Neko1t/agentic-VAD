from src.core.schemas import (
    CalibrationResult,
    EpisodeSummary,
    MemoryCaseType,
    MemoryWriteDecision,
    ObservationCard,
    RetrievedCase,
    RetrievalResult,
    RollingSummaryState,
    RunMode,
    TimeSpan,
)
from src.memory.policy import MemoryPolicy


def _episode() -> EpisodeSummary:
    return EpisodeSummary(
        video_id="video_1",
        segment_span=TimeSpan(start_frame=0, end_frame=31),
        story_text="A person runs and falls in a street scene.",
        action_sequence="run -> fall",
        score_story=8.2,
        score_memory_adjusted=8.3,
    )


def _state() -> RollingSummaryState:
    return RollingSummaryState(
        video_id="video_1",
        current_scene="outdoor street scene",
        active_entities=["person"],
        event_chain=["run", "fall"],
    )


def _observation(score: float = 8.5, uncertainty: float = 0.1) -> ObservationCard:
    return ObservationCard(
        video_id="video_1",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=16, end_frame=31),
        vision_caption="A person runs and falls.",
        entities=["person"],
        actions=["run", "fall"],
        scene_context="outdoor street scene",
        score_raw=score,
        score_weighted=score,
        uncertainty=uncertainty,
    )


def test_memory_policy_writes_high_risk_case():
    policy = MemoryPolicy(write_threshold=8.0)
    event = policy.decide(
        episode=_episode(),
        state=_state(),
        calibration=CalibrationResult(
            score_local=8.5,
            score_story=8.2,
            score_memory_adjusted=8.3,
            final_score=8.4,
        ),
        observations=[_observation()],
        retrieval=RetrievalResult(),
        run_mode=RunMode.ONLINE_INFERENCE,
    )

    assert event.decision == MemoryWriteDecision.WRITE
    assert event.case_type == MemoryCaseType.HIGH_RISK
    assert event.case_record is not None
    assert event.case_record.provisional is True
    assert event.case_record.case_type == MemoryCaseType.HIGH_RISK
    assert event.case_record.evidence_tags == ["run", "fall"]


def test_memory_policy_writes_hard_negative_case():
    policy = MemoryPolicy()
    event = policy.decide(
        episode=_episode(),
        state=_state(),
        calibration=CalibrationResult(
            score_local=7.8,
            score_story=2.5,
            score_memory_adjusted=2.6,
            final_score=2.7,
        ),
        observations=[_observation(score=7.8, uncertainty=0.5)],
        retrieval=RetrievalResult(),
        run_mode=RunMode.ONLINE_INFERENCE,
    )

    assert event.decision == MemoryWriteDecision.WRITE
    assert event.case_type == MemoryCaseType.HARD_NEGATIVE
    assert event.case_record is not None
    assert event.case_record.label == "hard_negative"
    assert event.case_record.local_score == 7.8
    assert event.case_record.final_score == 2.7


def test_memory_policy_skips_offline_eval():
    policy = MemoryPolicy()
    event = policy.decide(
        episode=_episode(),
        state=_state(),
        calibration=CalibrationResult(
            score_local=9.0,
            score_story=9.0,
            score_memory_adjusted=9.0,
            final_score=9.0,
        ),
        observations=[_observation()],
        retrieval=RetrievalResult(),
        run_mode=RunMode.OFFLINE_EVAL,
    )

    assert event.decision == MemoryWriteDecision.SKIP
    assert event.case_record is None
    assert "eval_mode_no_write" in event.skip_codes


def test_memory_policy_updates_duplicate_instead_of_writing():
    policy = MemoryPolicy(duplicate_similarity_threshold=0.95)
    event = policy.decide(
        episode=_episode(),
        state=_state(),
        calibration=CalibrationResult(
            score_local=8.8,
            score_story=8.8,
            score_memory_adjusted=8.8,
            final_score=8.8,
        ),
        observations=[_observation()],
        retrieval=RetrievalResult(
            similar_cases=[
                RetrievedCase(
                    case_id="case_existing",
                    video_id="video_old",
                    score=0.97,
                    episode_summary="Similar run fall case.",
                    action_sequence="run -> fall",
                    risk_score=8.5,
                )
            ]
        ),
        run_mode=RunMode.ONLINE_INFERENCE,
    )

    assert event.decision == MemoryWriteDecision.UPDATE_EXISTING
    assert event.duplicate_of == "case_existing"
    assert "semantic_duplicate" in event.skip_codes
