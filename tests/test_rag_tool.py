from pathlib import Path

from src.core.schemas import CaseMemoryRecord, MemoryCaseType, RetrievalQuery, TimeSpan
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.pattern_store import PatternMemoryStore
from src.memory.session_store import SessionMemoryStore
from src.tools.rag_tool import RAGTool


def _case(case_id: str, video_id: str, text: str, provisional: bool) -> CaseMemoryRecord:
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
        outcome="rag candidate",
        embedding_text=text,
        provisional=provisional,
        case_type=MemoryCaseType.HIGH_RISK,
    )


def test_rag_tool_merges_session_memory_with_persistent_memory(tmp_path: Path):
    embedding_builder = EmbeddingBuilder()
    case_store = CaseMemoryStore(
        storage_dir=tmp_path,
        collection_name="case_memory",
        provisional_collection_name="provisional_case_memory",
        embedding_builder=embedding_builder,
        use_chroma=False,
    )
    case_store.add_case(_case("case_final", "video_old", "run fall crowd outdoor", provisional=False))
    session_store = SessionMemoryStore(embedding_builder)
    session_store.add_case(_case("case_session", "video_1", "run fall outdoor street suspicious", provisional=True))
    rag_tool = RAGTool(
        case_store=case_store,
        pattern_store=PatternMemoryStore(tmp_path / "pattern_memory.jsonl"),
        session_store=session_store,
    )

    result = rag_tool.rag_retrieve(
        RetrievalQuery(
            video_id="video_1",
            action_sequence="run -> fall",
            evidence_tags=["run", "fall"],
            scene_type="outdoor street scene",
        ),
        top_k=5,
    )

    case_ids = {case.case_id for case in result.similar_cases}
    assert {"case_final", "case_session"} <= case_ids
    assert any(case.metadata.get("source") == "session_memory" for case in result.similar_cases)
