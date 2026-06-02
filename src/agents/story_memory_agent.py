from __future__ import annotations

from typing import Sequence, Tuple

from src.core.schemas import EpisodeSummary, ObservationCard, RetrievalQuery, RollingSummaryState, TimeSpan
from src.tools.rag_tool import RAGTool
from src.tools.score_tool import ScoreTool


class StoryMemoryAgent:
    def __init__(
        self,
        rag_tool: RAGTool,
        score_tool: ScoreTool,
        rolling_window_size: int = 4,
        top_k: int = 5,
    ):
        self.rag_tool = rag_tool
        self.score_tool = score_tool
        self.rolling_window_size = rolling_window_size
        self.top_k = top_k

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
            action_sequence=action_sequence,
            evidence_tags=list({action for card in bounded_cards for action in card.actions}),
            scene_type=updated_state.current_scene,
            story_text=story_text,
        )
        retrieval = self.rag_tool.rag_retrieve(query, top_k=self.top_k)
        score_story = min(10.0, max(card.score_weighted for card in bounded_cards) * 0.6 + (sum(card.score_weighted for card in bounded_cards) / len(bounded_cards)) * 0.4)
        calibration = self.score_tool.fuse_scores(
            score_local=max(card.score_weighted for card in bounded_cards),
            score_story=score_story,
            retrieval_confidence=retrieval.retrieval_confidence,
            similar_cases=retrieval.similar_cases,
            matched_patterns=retrieval.matched_patterns,
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
        return episode, updated_state
