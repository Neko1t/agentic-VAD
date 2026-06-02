from pathlib import Path

from src.agents.story_memory_agent import StoryMemoryAgent
from src.core.config import ScoringConfig
from src.core.schemas import ModalityConfidence, ObservationCard, TimeSpan
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.pattern_store import PatternMemoryStore
from src.tools.rag_tool import RAGTool
from src.tools.score_tool import ScoreTool


def _card(window_id: str, start_frame: int, action: str, score: float) -> ObservationCard:
    return ObservationCard(
        video_id="video_1",
        window_id=window_id,
        time_span=TimeSpan(start_frame=start_frame, end_frame=start_frame + 15),
        vision_caption=f"A person may {action}.",
        actions=[action],
        entities=["person"],
        scene_context="outdoor street scene",
        modality_confidence=ModalityConfidence(vision_conf=0.9, audio_conf=0.0, ocr_conf=0.0),
        score_raw=score,
        score_weighted=score,
    )


def test_story_memory_agent_uses_rolling_summary(tmp_path: Path):
    case_store = CaseMemoryStore(
        storage_dir=tmp_path,
        collection_name="case_memory",
        provisional_collection_name="provisional_case_memory",
        embedding_builder=EmbeddingBuilder(),
        use_chroma=False,
    )
    pattern_store = PatternMemoryStore(tmp_path / "pattern_memory.jsonl")
    agent = StoryMemoryAgent(
        rag_tool=RAGTool(case_store=case_store, pattern_store=pattern_store),
        score_tool=ScoreTool(ScoringConfig()),
        rolling_window_size=2,
        top_k=3,
    )
    state = agent.initialize_state("video_1")
    cards = [
        _card("w1", 0, "walk", 2.0),
        _card("w2", 16, "run", 6.0),
        _card("w3", 32, "fall", 8.0),
    ]
    episode, new_state = agent.summarize_episode(state, cards[-2:])
    assert "run -> fall" in episode.action_sequence
    assert new_state.event_chain[-2:] == ["run", "fall"]
