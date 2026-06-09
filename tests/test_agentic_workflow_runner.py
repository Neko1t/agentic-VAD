import json
from pathlib import Path

from src.core.schemas import RunMode
from src.pipelines.run_agentic_vad import run_pipeline
from src.pipelines.run_agentic_workflow import WorkflowStage, compare_metric_reports, run_workflow
from src.runtime.progress import NullProgressReporter


class _CaptureReporter(NullProgressReporter):
    def __init__(self):
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


def _prepare_tiny_dataset(tmp_path: Path) -> dict[str, Path]:
    root_path = tmp_path / "dataset"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "outputs"
    memory_dir = tmp_path / "memory"
    root_path.mkdir()
    captions_dir.mkdir()
    annotation_file = tmp_path / "test.txt"
    temporal_annotation_file = tmp_path / "temporal.txt"
    annotation_file.write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    temporal_annotation_file.write_text("video_1.mp4 0 0 31\n", encoding="utf-8")
    (captions_dir / "video_1.json").write_text(
        json.dumps(
            {
                "0": "A person walks on a street.",
                "16": "A person runs and falls on a street.",
            }
        ),
        encoding="utf-8",
    )
    baseline_scores_dir = tmp_path / "baseline_scores"
    baseline_scores_dir.mkdir()
    (baseline_scores_dir / "video_1.json").write_text(
        json.dumps({"0": 0.15, "16": 0.85}, indent=2),
        encoding="utf-8",
    )
    return {
        "root_path": root_path,
        "captions_dir": captions_dir,
        "output_dir": output_dir,
        "memory_dir": memory_dir,
        "annotation_file": annotation_file,
        "temporal_annotation_file": temporal_annotation_file,
        "baseline_scores_dir": baseline_scores_dir,
    }


def test_run_pipeline_emits_fine_grained_progress_events(tmp_path: Path):
    paths = _prepare_tiny_dataset(tmp_path)
    reporter = _CaptureReporter()

    summary = run_pipeline(
        root_path=paths["root_path"],
        annotation_file_path=paths["annotation_file"],
        captions_dir=paths["captions_dir"],
        output_dir=paths["output_dir"],
        memory_dir=paths["memory_dir"],
        frame_interval=16,
        rolling_window_size=2,
        use_audio=False,
        use_ocr=False,
        top_k=3,
        run_mode=RunMode.ONLINE_INFERENCE,
        use_chroma=False,
        progress_reporter=reporter,
    )

    assert summary["windows_processed"] == 2
    tool_names = [event.tool_name for event in reporter.events if event.tool_name]
    assert "vlm_describe" in tool_names
    assert "score_observation" in tool_names
    assert "rag_retrieve" in tool_names
    assert "fuse_scores" in tool_names
    assert any(event.event == "window_end" for event in reporter.events)


def test_run_workflow_writes_comparison_outputs(tmp_path: Path):
    paths = _prepare_tiny_dataset(tmp_path)
    reporter = _CaptureReporter()

    summary = run_workflow(
        root_path=paths["root_path"],
        annotation_file_path=paths["annotation_file"],
        captions_dir=paths["captions_dir"],
        output_dir=paths["output_dir"],
        memory_dir=paths["memory_dir"],
        temporal_annotation_file=paths["temporal_annotation_file"],
        baseline_scores_dir=paths["baseline_scores_dir"],
        stages=[
            WorkflowStage.PIPELINE,
            WorkflowStage.METRICS,
            WorkflowStage.BASELINE_METRICS,
            WorkflowStage.COMPARE,
        ],
        frame_interval=16,
        rolling_window_size=2,
        top_k=3,
        use_chroma=False,
        progress_reporter=reporter,
    )

    comparison_path = paths["output_dir"] / "comparison_report.json"
    workflow_summary_path = paths["output_dir"] / "workflow_summary.json"
    assert comparison_path.exists()
    assert workflow_summary_path.exists()
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert comparison["status"] == "ok"
    assert "roc_auc" in comparison["diff"]
    assert summary["compare"]["comparison_path"] == str(comparison_path)
    assert any(event.stage == "workflow" for event in reporter.events)


def test_compare_metric_reports_handles_missing_baseline():
    report = compare_metric_reports({"roc_auc": 0.9, "pr_auc": 0.8}, None)
    assert report["status"] == "baseline_unavailable"
    assert report["diff"]["roc_auc"]["delta"] is None
