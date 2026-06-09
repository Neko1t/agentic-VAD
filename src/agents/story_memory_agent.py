from __future__ import annotations

import time
from typing import List, Sequence, Tuple

from src.core.schemas import (
    CalibrationResult,
    EpisodeSummary,
    ObservationCard,
    RetrievalQuery,
    RetrievalResult,
    RollingSummaryState,
    StoryMemoryInput,
    StoryMemoryResult,
    TimeSpan,
    ToolCallRecord,
)
from src.memory.policy import MemoryPolicy
from src.runtime.progress import ProgressEvent
from src.tools.rag_tool import RAGTool
from src.tools.score_tool import ScoreTool


class StoryMemoryAgent:
    def __init__(
        self,
        rag_tool: RAGTool,
        score_tool: ScoreTool,
        memory_policy: MemoryPolicy | None = None,
        rolling_window_size: int = 4,
        top_k: int = 5,
        progress_callback=None,
    ):
        self.rag_tool = rag_tool
        self.score_tool = score_tool
        self.memory_policy = memory_policy or MemoryPolicy()
        self.rolling_window_size = rolling_window_size
        self.top_k = top_k
        self.progress_callback = progress_callback

    def initialize_state(self, video_id: str) -> RollingSummaryState:
        return RollingSummaryState(video_id=video_id)

    def update_rolling_summary(
        self,
        state: RollingSummaryState,
        new_cards: Sequence[ObservationCard],
    ) -> RollingSummaryState:
        if not new_cards:
            return state
        current_scene = new_cards[-1].scene_context or state.current_scene
        active_entities = list(dict.fromkeys(state.active_entities + [entity for card in new_cards for entity in card.entities]))[-12:]
        event_chain = (state.event_chain + [action for card in new_cards for action in card.actions])[-20:]
        risk_evolution = (state.risk_evolution + [card.score_weighted for card in new_cards])[-20:]
        evidence_highlights = (
            state.evidence_highlights
            + [
                f"{card.window_id}: {card.vision_caption}"
                for card in new_cards
                if card.vision_caption
            ]
        )[-10:]
        open_questions = list(state.open_questions)
        if risk_evolution and risk_evolution[-1] >= 7.0:
            open_questions = ["confirm anomaly escalation"] + open_questions
        return RollingSummaryState(
            video_id=state.video_id,
            current_scene=current_scene,
            active_entities=active_entities,
            event_chain=event_chain,
            risk_evolution=risk_evolution,
            open_questions=open_questions[:5],
            evidence_highlights=evidence_highlights,
        )

    def summarize_episode(
        self,
        state: RollingSummaryState,
        recent_cards: Sequence[ObservationCard],
    ) -> Tuple[EpisodeSummary, RollingSummaryState]:
        episode, updated_state, _, _, _ = self._analyze_episode(state, recent_cards, self.top_k)
        return episode, updated_state

    def process(self, story_input: StoryMemoryInput) -> StoryMemoryResult:
        episode, updated_state, retrieval, calibration, bounded_cards = self._analyze_episode(
            story_input.state,
            story_input.recent_observations,
            story_input.top_k,
        )
        disagreement_score, contradiction_flags = self._detect_disagreement(calibration, retrieval)
        memory_event = self._call_tool(
            tool_name="memory_policy",
            video_id=story_input.video_id,
            window_id=bounded_cards[-1].window_id,
            input_summary=episode.action_sequence,
            call=lambda: self.memory_policy.decide(
                episode=episode,
                state=updated_state,
                calibration=calibration,
                observations=bounded_cards,
                retrieval=retrieval,
                run_mode=story_input.run_mode,
            ),
        )
        return StoryMemoryResult(
            video_id=story_input.video_id,
            episode=episode,
            state=updated_state,
            retrieval=retrieval,
            calibration=calibration,
            memory_event=memory_event,
            disagreement_score=disagreement_score,
            contradiction_flags=contradiction_flags,
            tool_trace=[
                ToolCallRecord(
                    tool_name="rag_retrieve",
                    input_summary=episode.action_sequence,
                    output_summary=f"{len(retrieval.similar_cases)} cases, {len(retrieval.matched_patterns)} patterns",
                    confidence=retrieval.retrieval_confidence,
                ),
                ToolCallRecord(
                    tool_name="fuse_scores",
                    input_summary=f"local={calibration.score_local:.2f}, story={calibration.score_story:.2f}",
                    output_summary=f"final={calibration.final_score:.2f}",
                ),
            ],
        )

    def _analyze_episode(
        self,
        state: RollingSummaryState,
        recent_cards: Sequence[ObservationCard],
        top_k: int,
    ) -> Tuple[EpisodeSummary, RollingSummaryState, RetrievalResult, CalibrationResult, List[ObservationCard]]:
        if not recent_cards:
            raise ValueError("recent_cards must not be empty")
        bounded_cards = list(recent_cards)[-self.rolling_window_size :]
        updated_state = self.update_rolling_summary(state, bounded_cards)
        action_sequence = " -> ".join(updated_state.event_chain[-self.rolling_window_size :]) or "no_clear_action"
        story_text = " ".join(
            [
                f"In {updated_state.current_scene}, "
                f"entities {', '.join(updated_state.active_entities[-5:]) or 'unknown'} "
                f"show actions {action_sequence}.",
                f"Recent evidence: {' | '.join(updated_state.evidence_highlights[-3:])}",
            ]
        ).strip()
        query = RetrievalQuery(
            video_id=updated_state.video_id,
            action_sequence=action_sequence,
            evidence_tags=list({action for card in bounded_cards for action in card.actions}),
            scene_type=updated_state.current_scene,
            story_text=story_text,
        )
        retrieval = self._call_tool(
            tool_name="rag_retrieve",
            video_id=updated_state.video_id,
            window_id=bounded_cards[-1].window_id,
            input_summary=action_sequence,
            call=lambda: self.rag_tool.rag_retrieve(query, top_k=top_k),
        )
        score_story = min(10.0, max(card.score_weighted for card in bounded_cards) * 0.6 + (sum(card.score_weighted for card in bounded_cards) / len(bounded_cards)) * 0.4)
        calibration = self._call_tool(
            tool_name="fuse_scores",
            video_id=updated_state.video_id,
            window_id=bounded_cards[-1].window_id,
            input_summary=f"{action_sequence} | local={max(card.score_weighted for card in bounded_cards):.2f}",
            call=lambda: self.score_tool.fuse_scores(
                score_local=max(card.score_weighted for card in bounded_cards),
                score_story=score_story,
                retrieval_confidence=retrieval.retrieval_confidence,
                similar_cases=retrieval.similar_cases,
                matched_patterns=retrieval.matched_patterns,
            ),
        )
        span = TimeSpan(
            start_frame=bounded_cards[0].time_span.start_frame,
            end_frame=bounded_cards[-1].time_span.end_frame,
            start_time=bounded_cards[0].time_span.start_time,
            end_time=bounded_cards[-1].time_span.end_time,
        )
        episode = EpisodeSummary(
            video_id=bounded_cards[0].video_id,
            segment_span=span,
            story_text=story_text,
            action_sequence=action_sequence,
            risk_hints=calibration.calibration_reason,
            retrieved_case_ids=[case.case_id for case in retrieval.similar_cases],
            matched_pattern_ids=[pattern.pattern_id for pattern in retrieval.matched_patterns],
            score_story=score_story,
            score_memory_adjusted=calibration.score_memory_adjusted,
        )
        return episode, updated_state, retrieval, calibration, bounded_cards

    def _detect_disagreement(
        self,
        calibration: CalibrationResult,
        retrieval: RetrievalResult,
    ) -> Tuple[float, List[str]]:
        disagreement_score = min(1.0, abs(calibration.score_local - calibration.final_score) / 10.0)
        flags: List[str] = []
        if calibration.score_local >= 7.0 and calibration.final_score <= 3.0:
            flags.append("local_high_final_low")
        if calibration.score_local <= 3.0 and calibration.final_score >= 7.0:
            flags.append("local_low_final_high")
        if retrieval.similar_cases and retrieval.retrieval_confidence >= 0.75:
            flags.append("strong_memory_match")
        if retrieval.matched_patterns:
            flags.append("pattern_match")
        return disagreement_score, flags

    def _call_tool(
        self,
        tool_name: str,
        video_id: str,
        window_id: str,
        input_summary: str,
        call,
    ):
        self._emit_progress(
            ProgressEvent(
                stage="story_memory",
                event="tool_start",
                tool_name=tool_name,
                video_id=video_id,
                window_id=window_id,
                message="running",
            )
        )
        started = time.perf_counter()
        try:
            result = call()
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._emit_progress(
                ProgressEvent(
                    stage="story_memory",
                    event="tool_error",
                    tool_name=tool_name,
                    video_id=video_id,
                    window_id=window_id,
                    message=f"error {latency_ms:.1f}ms",
                    metadata={"input_summary": input_summary, "error": f"{exc.__class__.__name__}: {exc}"},
                )
            )
            raise
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._emit_progress(
            ProgressEvent(
                stage="story_memory",
                event="tool_end",
                tool_name=tool_name,
                video_id=video_id,
                window_id=window_id,
                message=f"done {latency_ms:.1f}ms",
                metadata={"input_summary": input_summary, "latency_ms": round(latency_ms, 3)},
            )
        )
        return result

    def _emit_progress(self, event: ProgressEvent) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event)
