import inspect
import json

from src.core.schemas import (
    CalibrationResult,
    EpisodeSummary,
    MemoryWriteDecision,
    MemoryWriteEvent,
    ObservationCard,
    RetrievalResult,
    RollingSummaryState,
    RunMode,
    StoryMemoryResult,
    TimeSpan,
)
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.pipelines import run_agentic_vad
from src.pipelines.run_agentic_vad import _build_report


def test_pipeline_report_uses_story_memory_result_final_score():
    observation = ObservationCard(
        video_id="video_1",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
        vision_caption="A person falls.",
        score_weighted=4.0,
    )
    episode = EpisodeSummary(
        video_id="video_1",
        segment_span=TimeSpan(start_frame=0, end_frame=15),
        story_text="A person falls in a street scene.",
        action_sequence="fall",
        retrieved_case_ids=["case_1"],
        matched_pattern_ids=["pattern_1"],
        score_story=8.0,
        score_memory_adjusted=8.0,
    )
    result = StoryMemoryResult(
        video_id="video_1",
        episode=episode,
        state=RollingSummaryState(video_id="video_1"),
        retrieval=RetrievalResult(),
        calibration=CalibrationResult(
            score_local=4.0,
            score_story=8.0,
            score_memory_adjusted=8.0,
            final_score=8.2,
        ),
        memory_event=MemoryWriteEvent(decision=MemoryWriteDecision.WRITE),
    )

    report = _build_report(
        video_id="video_1",
        observations=[observation],
        story_results=[result],
        threshold=6.5,
    )

    assert report.segment_scores == [8.2]
    assert len(report.abnormal_segments) == 1
    assert report.retrieved_cases == ["case_1"]
    assert report.matched_patterns == ["pattern_1"]


def test_pipeline_no_longer_builds_case_memory_directly():
    source = inspect.getsource(run_agentic_vad)
    assert "def _build_case_record" not in source
    assert "StoryMemoryInput" in source
    assert "MemoryWriteDecision.WRITE" in source
    assert "SessionMemoryStore" in source
    assert "rag_store_session" in source
    assert "export_eval_scores" in source
    assert "_build_eval_scores" in source


def test_agentic_pipeline_runs_tiny_mocked_dataset(tmp_path):
    root_path = tmp_path / "dataset"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "outputs"
    memory_dir = tmp_path / "memory"
    root_path.mkdir()
    captions_dir.mkdir()
    annotation_file = tmp_path / "test.txt"
    annotation_file.write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (captions_dir / "video_1.json").write_text(
        json.dumps(
            {
                "0": "A person walks on a street.",
                "16": "A person runs and falls on a street.",
            }
        ),
        encoding="utf-8",
    )

    run_agentic_vad.main(
        root_path=root_path,
        annotation_file_path=annotation_file,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        frame_interval=16,
        rolling_window_size=2,
        use_audio=False,
        use_ocr=False,
        top_k=3,
        run_mode=RunMode.ONLINE_INFERENCE,
        use_chroma=False,
    )

    report_path = output_dir / "reports" / "video_1.json"
    observation_path = output_dir / "observations" / "video_1.json"
    episode_path = output_dir / "episodes" / "video_1.json"
    story_result_path = output_dir / "story_results" / "video_1.json"
    score_path = output_dir / "scores" / "video_1.json"
    assert report_path.exists()
    assert observation_path.exists()
    assert episode_path.exists()
    assert story_result_path.exists()
    assert score_path.exists()

    observations = json.loads(observation_path.read_text(encoding="utf-8"))
    story_results = json.loads(story_result_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    exported_scores = json.loads(score_path.read_text(encoding="utf-8"))
    assert len(observations) == 2
    assert len(story_results) == 2
    assert observations[0]["tool_trace"]
    assert story_results[-1]["memory_event"]["decision"] == "write"
    assert report["abnormal_segments"]
    assert sorted(exported_scores.keys()) == ["0", "16"]
    assert all(0.0 <= value <= 1.0 for value in exported_scores.values())

    store = CaseMemoryStore(
        storage_dir=memory_dir,
        collection_name="case_memory",
        provisional_collection_name="provisional_case_memory",
        embedding_builder=EmbeddingBuilder(),
        use_chroma=False,
    )
    provisional_cases = store.list_cases(provisional=True)
    assert provisional_cases
    assert provisional_cases[0].video_id == "video_1"
