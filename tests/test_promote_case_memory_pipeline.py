from pathlib import Path

from src.core.schemas import CaseMemoryRecord, MemoryCaseType, TimeSpan
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.pipelines.promote_case_memory import promote_cases


def _store(tmp_path: Path) -> CaseMemoryStore:
    return CaseMemoryStore(
        storage_dir=tmp_path,
        collection_name="case_memory",
        provisional_collection_name="provisional_case_memory",
        embedding_builder=EmbeddingBuilder(),
        use_chroma=False,
    )


def _case(case_id: str, risk_score: float, uncertainty: float = 0.1) -> CaseMemoryRecord:
    return CaseMemoryRecord(
        case_id=case_id,
        video_id="video_1",
        time_span=TimeSpan(start_frame=0, end_frame=31),
        label="high_risk",
        risk_score=risk_score,
        episode_summary="A person runs and falls.",
        action_sequence="run -> fall",
        key_entities=["person"],
        scene_type="outdoor street scene",
        evidence_tags=["run", "fall"],
        outcome="candidate",
        embedding_text="run fall outdoor street",
        provisional=True,
        case_type=MemoryCaseType.HIGH_RISK,
        uncertainty=uncertainty,
        local_score=risk_score,
        final_score=risk_score,
    )


def test_promote_cases_dry_run_does_not_modify_store(tmp_path: Path):
    store = _store(tmp_path)
    store.add_case(_case("case_1", risk_score=8.5))

    report = promote_cases(memory_dir=tmp_path, dry_run=True)

    assert report["counts"]["promoted"] == 1
    assert store.list_cases(provisional=True)[0].case_id == "case_1"
    assert store.list_cases(provisional=False) == []


def test_promote_cases_promotes_eligible_cases_only(tmp_path: Path):
    store = _store(tmp_path)
    store.add_case(_case("case_good", risk_score=8.5))
    store.add_case(_case("case_uncertain", risk_score=9.0, uncertainty=0.9))

    report = promote_cases(memory_dir=tmp_path, dry_run=False)

    promoted_ids = {record.case_id for record in store.list_cases(provisional=False)}
    provisional_ids = {record.case_id for record in store.list_cases(provisional=True)}
    assert report["promoted"] == ["case_good"]
    assert promoted_ids == {"case_good"}
    assert provisional_ids == {"case_uncertain"}
    assert report["counts"]["skipped"] == 1
    assert report["skipped"][0]["case_id"] == "case_uncertain"


def test_promote_cases_respects_case_id_filter(tmp_path: Path):
    store = _store(tmp_path)
    store.add_case(_case("case_selected", risk_score=8.5))
    store.add_case(_case("case_other", risk_score=8.5))

    report = promote_cases(memory_dir=tmp_path, case_ids=["case_selected"], dry_run=False)

    promoted_ids = {record.case_id for record in store.list_cases(provisional=False)}
    provisional_ids = {record.case_id for record in store.list_cases(provisional=True)}
    assert report["promoted"] == ["case_selected"]
    assert promoted_ids == {"case_selected"}
    assert provisional_ids == {"case_other"}
