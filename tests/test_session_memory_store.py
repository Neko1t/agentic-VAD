from src.core.schemas import CaseMemoryRecord, MemoryCaseType, RetrievalQuery, TimeSpan
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.session_store import SessionMemoryStore


def _case(case_id: str, video_id: str, text: str) -> CaseMemoryRecord:
    return CaseMemoryRecord(
        case_id=case_id,
        video_id=video_id,
        time_span=TimeSpan(start_frame=0, end_frame=31),
        label="high_risk",
        risk_score=8.5,
        episode_summary=text,
        action_sequence="run -> fall",
        key_entities=["person"],
        scene_type="outdoor street scene",
        evidence_tags=["run", "fall"],
        outcome="session candidate",
        embedding_text=text,
        provisional=True,
        case_type=MemoryCaseType.HIGH_RISK,
    )


def test_session_memory_retrieves_only_current_video_cases():
    store = SessionMemoryStore(EmbeddingBuilder())
    store.add_case(_case("case_1", "video_1", "run fall outdoor street suspicious"))
    store.add_case(_case("case_2", "video_2", "run fall outdoor street suspicious"))

    result = store.retrieve(
        RetrievalQuery(
            video_id="video_1",
            action_sequence="run -> fall",
            evidence_tags=["run", "fall"],
            scene_type="outdoor street scene",
        )
    )

    assert [case.case_id for case in result.similar_cases] == ["case_1"]
    assert result.similar_cases[0].metadata["source"] == "session_memory"


def test_session_memory_can_clear_video_cases():
    store = SessionMemoryStore(EmbeddingBuilder())
    store.add_case(_case("case_1", "video_1", "run fall outdoor street suspicious"))
    store.add_case(_case("case_2", "video_2", "run fall outdoor street suspicious"))

    store.clear_video("video_1")

    assert [case.case_id for case in store.list_cases()] == ["case_2"]
