from __future__ import annotations

from typing import List, Optional

from src.core.schemas import (
    CalibrationResult,
    CaseMemoryRecord,
    EpisodeSummary,
    MemoryCaseType,
    MemoryWriteDecision,
    MemoryWriteEvent,
    ObservationCard,
    RetrievalResult,
    RollingSummaryState,
    RunMode,
)


class MemoryPolicy:
    def __init__(
        self,
        write_threshold: float = 8.0,
        hard_negative_local_threshold: float = 7.0,
        hard_negative_final_threshold: float = 3.0,
        uncertainty_threshold: float = 0.3,
        ambiguous_min_score: float = 5.0,
        disagreement_threshold: float = 0.35,
        duplicate_similarity_threshold: float = 0.95,
    ):
        self.write_threshold = write_threshold
        self.hard_negative_local_threshold = hard_negative_local_threshold
        self.hard_negative_final_threshold = hard_negative_final_threshold
        self.uncertainty_threshold = uncertainty_threshold
        self.ambiguous_min_score = ambiguous_min_score
        self.disagreement_threshold = disagreement_threshold
        self.duplicate_similarity_threshold = duplicate_similarity_threshold

    def decide(
        self,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
        observations: List[ObservationCard],
        retrieval: RetrievalResult,
        run_mode: RunMode,
    ) -> MemoryWriteEvent:
        if run_mode == RunMode.OFFLINE_EVAL:
            return MemoryWriteEvent(
                decision=MemoryWriteDecision.SKIP,
                reason="memory writes are disabled during offline evaluation",
                skip_codes=["eval_mode_no_write"],
            )

        duplicate = self._find_duplicate(retrieval)
        if duplicate is not None:
            case_id, similarity = duplicate
            return MemoryWriteEvent(
                decision=MemoryWriteDecision.UPDATE_EXISTING,
                reason="similar finalized case already exists",
                skip_codes=["semantic_duplicate"],
                duplicate_of=case_id,
                similarity_to_existing=similarity,
            )

        uncertainty = self._latest_uncertainty(observations)
        if calibration.final_score >= self.write_threshold and uncertainty <= self.uncertainty_threshold:
            return self._write_event(
                case_type=MemoryCaseType.HIGH_RISK,
                reason="high final score with low uncertainty",
                episode=episode,
                state=state,
                calibration=calibration,
                observations=observations,
                retrieval=retrieval,
                uncertainty=uncertainty,
                run_mode=run_mode,
            )

        if (
            calibration.score_local >= self.hard_negative_local_threshold
            and calibration.final_score <= self.hard_negative_final_threshold
        ):
            return self._write_event(
                case_type=MemoryCaseType.HARD_NEGATIVE,
                reason="local evidence was high risk but calibrated final risk was low",
                episode=episode,
                state=state,
                calibration=calibration,
                observations=observations,
                retrieval=retrieval,
                uncertainty=uncertainty,
                run_mode=run_mode,
            )

        disagreement = abs(calibration.score_local - calibration.final_score) / 10.0
        if calibration.final_score >= self.ambiguous_min_score and disagreement >= self.disagreement_threshold:
            return self._write_event(
                case_type=MemoryCaseType.AMBIGUOUS,
                reason="score disagreement is informative enough to keep as provisional memory",
                episode=episode,
                state=state,
                calibration=calibration,
                observations=observations,
                retrieval=retrieval,
                uncertainty=uncertainty,
                run_mode=run_mode,
            )

        return MemoryWriteEvent(
            decision=MemoryWriteDecision.SKIP,
            reason="segment did not pass memory admission gates",
            skip_codes=["low_information_value"],
        )

    def _write_event(
        self,
        case_type: MemoryCaseType,
        reason: str,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
        observations: List[ObservationCard],
        retrieval: RetrievalResult,
        uncertainty: float,
        run_mode: RunMode,
    ) -> MemoryWriteEvent:
        return MemoryWriteEvent(
            decision=MemoryWriteDecision.WRITE,
            case_type=case_type,
            reason=reason,
            case_record=self._build_case_record(
                case_type=case_type,
                episode=episode,
                state=state,
                calibration=calibration,
                observations=observations,
                retrieval=retrieval,
                uncertainty=uncertainty,
                run_mode=run_mode,
            ),
        )

    def _build_case_record(
        self,
        case_type: MemoryCaseType,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
        observations: List[ObservationCard],
        retrieval: RetrievalResult,
        uncertainty: float,
        run_mode: RunMode,
    ) -> CaseMemoryRecord:
        evidence_tags = self._evidence_tags(episode, observations)
        entities = list(dict.fromkeys(state.active_entities))[:10]
        source = run_mode.value
        return CaseMemoryRecord(
            case_id=f"{episode.video_id}_{episode.segment_span.start_frame}_{episode.segment_span.end_frame}",
            video_id=episode.video_id,
            time_span=episode.segment_span,
            label=case_type.value,
            risk_score=calibration.final_score,
            episode_summary=episode.story_text,
            action_sequence=episode.action_sequence,
            key_entities=entities,
            scene_type=state.current_scene,
            evidence_tags=evidence_tags,
            outcome=f"{case_type.value} generated by memory policy",
            embedding_text=" | ".join(
                part
                for part in [
                    episode.action_sequence,
                    state.current_scene,
                    " ".join(evidence_tags),
                    episode.story_text,
                ]
                if part
            ),
            provisional=True,
            case_type=case_type,
            source=source,
            uncertainty=uncertainty,
            local_score=calibration.score_local,
            final_score=calibration.final_score,
            retrieval_case_ids=[case.case_id for case in retrieval.similar_cases],
            matched_pattern_ids=[pattern.pattern_id for pattern in retrieval.matched_patterns],
        )

    def _find_duplicate(self, retrieval: RetrievalResult) -> Optional[tuple[str, float]]:
        for case in retrieval.similar_cases:
            if case.score >= self.duplicate_similarity_threshold:
                return case.case_id, case.score
        return None

    def _latest_uncertainty(self, observations: List[ObservationCard]) -> float:
        if not observations:
            return 1.0
        return observations[-1].uncertainty

    def _evidence_tags(self, episode: EpisodeSummary, observations: List[ObservationCard]) -> List[str]:
        tags = [token.strip() for token in episode.action_sequence.split("->") if token.strip()]
        for observation in observations:
            tags.extend(action.strip() for action in observation.actions if action.strip())
            tags.extend(event.strip() for event in observation.audio_events if event.strip())
        return list(dict.fromkeys(tags))[:20]
