from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from src.core.schemas import CaseMemoryRecord, MemoryCaseType


class PromotionDecision(BaseModel):
    should_promote: bool
    reason: str = ""
    skip_codes: List[str] = Field(default_factory=list)


class MemoryPromotionPolicy:
    def __init__(
        self,
        high_risk_threshold: float = 8.0,
        hard_negative_threshold: float = 2.5,
        max_uncertainty: float = 0.35,
        min_evidence_tags: int = 1,
    ):
        self.high_risk_threshold = high_risk_threshold
        self.hard_negative_threshold = hard_negative_threshold
        self.max_uncertainty = max_uncertainty
        self.min_evidence_tags = min_evidence_tags

    def decide(self, record: CaseMemoryRecord) -> PromotionDecision:
        if not record.provisional:
            return PromotionDecision(
                should_promote=False,
                reason="case is already finalized",
                skip_codes=["already_finalized"],
            )
        if record.uncertainty > self.max_uncertainty:
            return PromotionDecision(
                should_promote=False,
                reason="case uncertainty is too high for offline promotion",
                skip_codes=["high_uncertainty"],
            )
        if len(record.evidence_tags) < self.min_evidence_tags:
            return PromotionDecision(
                should_promote=False,
                reason="case does not have enough evidence tags",
                skip_codes=["insufficient_evidence_tags"],
            )
        if record.case_type == MemoryCaseType.HIGH_RISK and record.risk_score >= self.high_risk_threshold:
            return PromotionDecision(
                should_promote=True,
                reason="high-risk case passed promotion gates",
            )
        if (
            record.case_type == MemoryCaseType.HARD_NEGATIVE
            and record.local_score is not None
            and record.local_score >= self.high_risk_threshold
            and record.final_score is not None
            and record.final_score <= self.hard_negative_threshold
        ):
            return PromotionDecision(
                should_promote=True,
                reason="hard-negative case passed promotion gates",
            )
        return PromotionDecision(
            should_promote=False,
            reason="case did not match any promotion rule",
            skip_codes=["no_matching_promotion_rule"],
        )
