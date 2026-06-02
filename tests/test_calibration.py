from src.core.config import ScoringConfig
from src.core.schemas import RetrievedCase
from src.tools.score_tool import ScoreTool


def test_retrieval_guided_calibration_uses_memory_confidence():
    tool = ScoreTool(ScoringConfig())
    result = tool.fuse_scores(
        score_local=7.5,
        score_story=7.0,
        retrieval_confidence=0.8,
        similar_cases=[
            RetrievedCase(
                case_id="c1",
                video_id="v1",
                score=0.9,
                episode_summary="summary",
                action_sequence="run -> fall",
                risk_score=8.5,
                evidence_tags=["run", "fall"],
            )
        ],
        matched_patterns=[],
    )
    assert result.score_memory_adjusted >= 7.0
    assert result.final_score >= 7.0
