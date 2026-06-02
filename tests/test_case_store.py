from pathlib import Path

from src.core.schemas import CaseMemoryRecord, RetrievalQuery, TimeSpan
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder


def test_case_store_retrieves_similar_cases(tmp_path: Path):
    store = CaseMemoryStore(
        storage_dir=tmp_path,
        collection_name="case_memory",
        provisional_collection_name="provisional_case_memory",
        embedding_builder=EmbeddingBuilder(),
        use_chroma=False,
    )
    store.add_case(
        CaseMemoryRecord(
            case_id="case_1",
            video_id="video_1",
            time_span=TimeSpan(start_frame=0, end_frame=32),
            label="anomaly",
            risk_score=8.2,
            episode_summary="A person run and then fall in a crowd.",
            action_sequence="run -> fall -> crowd",
            key_entities=["person"],
            scene_type="outdoor street scene",
            evidence_tags=["run", "fall", "crowd"],
            outcome="suspicious",
            embedding_text="run fall crowd outdoor street suspicious",
            provisional=False,
        )
    )
    result = store.retrieve(
        RetrievalQuery(
            action_sequence="run -> fall -> crowd",
            evidence_tags=["run", "fall"],
            scene_type="outdoor street scene",
            story_text="A crowd forms after a person falls.",
        ),
        top_k=3,
    )
    assert result.similar_cases
    assert result.similar_cases[0].case_id == "case_1"
