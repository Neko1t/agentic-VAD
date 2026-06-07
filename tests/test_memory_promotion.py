from src.core.schemas import CaseMemoryRecord, MemoryCaseType, TimeSpan
from src.memory.promotion import MemoryPromotionPolicy


def _case(
    case_id: str = "case_1",
    case_type: MemoryCaseType = MemoryCaseType.HIGH_RISK,
    risk_score: float = 8.5,
    uncertainty: float = 0.1,
    local_score: float | None = 8.5,
    final_score: float | None = 8.5,
    evidence_tags: list[str] | None = None,
    provisional: bool = True,
) -> CaseMemoryRecord:
    return CaseMemoryRecord(
        case_id=case_id,
        video_id="video_1",
        time_span=TimeSpan(start_frame=0, end_frame=31),
        label=case_type.value,
        risk_score=risk_score,
        episode_summary="A useful case.",
        action_sequence="run -> fall",
        key_entities=["person"],
        scene_type="outdoor street scene",
        evidence_tags=evidence_tags if evidence_tags is not None else ["run", "fall"],
        outcome="candidate",
        embedding_text="run fall outdoor street",
        provisional=provisional,
        case_type=case_type,
        uncertainty=uncertainty,
        local_score=local_score,
        final_score=final_score,
    )


def test_promotion_policy_promotes_high_risk_case():
    decision = MemoryPromotionPolicy().decide(_case())

    assert decision.should_promote is True
    assert decision.skip_codes == []


def test_promotion_policy_promotes_hard_negative_case():
    decision = MemoryPromotionPolicy().decide(
        _case(
            case_type=MemoryCaseType.HARD_NEGATIVE,
            risk_score=2.2,
            local_score=8.2,
            final_score=2.2,
        )
    )

    assert decision.should_promote is True


def test_promotion_policy_skips_high_uncertainty_case():
    decision = MemoryPromotionPolicy(max_uncertainty=0.35).decide(_case(uncertainty=0.8))

    assert decision.should_promote is False
    assert "high_uncertainty" in decision.skip_codes


def test_promotion_policy_skips_already_finalized_case():
    decision = MemoryPromotionPolicy().decide(_case(provisional=False))

    assert decision.should_promote is False
    assert "already_finalized" in decision.skip_codes
