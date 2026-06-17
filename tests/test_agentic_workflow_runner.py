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


class _StubVideoLLaMABackend:
    name = "videollama3"

    def __init__(self, video_root=None, model_path=None, runtime_device=None):
        self.video_root = video_root
        self.model_path = model_path
        self.runtime_device = runtime_device

    def describe(self, window_input):
        return {
            "vision_caption": "A person runs through a street.",
            "confidence": 0.95,
            "backend_name": self.name,
            "artifact_refs": [str(self.video_root / f"{window_input.video_id}.mp4")],
        }

    def close(self):
        return None


def _prepare_tiny_dataset(tmp_path: Path) -> dict[str, Path]:
    root_path = tmp_path / "dataset"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "outputs"
    memory_dir = tmp_path / "memory"
    video_root_path = tmp_path / "videos"
    root_path.mkdir()
    captions_dir.mkdir()
    video_root_path.mkdir()
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
    (video_root_path / "video_1.mp4").write_bytes(b"fake")
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
        "video_root_path": video_root_path,
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
        gpu_device="0",
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
    assert summary["vlm_mode"] == "caption"
    tool_names = [event.tool_name for event in reporter.events if event.tool_name]
    assert "vlm_describe" in tool_names
    assert "score_observation" in tool_names
    assert "rag_retrieve" in tool_names
    assert "fuse_scores" in tool_names
    assert any(event.event == "window_end" for event in reporter.events)


def test_run_pipeline_uses_vlm_backend_when_requested(monkeypatch, tmp_path: Path):
    import src.pipelines.run_agentic_vad as pipeline_module

    paths = _prepare_tiny_dataset(tmp_path)
    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0", "1"])
    monkeypatch.setattr(pipeline_module, "VideoLLaMABackend", _StubVideoLLaMABackend)

    summary = run_pipeline(
        root_path=paths["root_path"],
        annotation_file_path=paths["annotation_file"],
        captions_dir=paths["captions_dir"],
        output_dir=paths["output_dir"],
        memory_dir=paths["memory_dir"],
        gpu_device="1",
        frame_interval=16,
        rolling_window_size=2,
        top_k=3,
        run_mode=RunMode.ONLINE_INFERENCE,
        use_chroma=False,
        use_vlm=True,
        video_root_path=paths["video_root_path"],
        vlm_model_path=tmp_path / "models" / "VideoLLaMA3-7B",
    )

    assert summary["windows_processed"] == 2
    assert summary["vlm_mode"] == "videollama3"


def test_run_workflow_writes_comparison_outputs(tmp_path: Path):
    paths = _prepare_tiny_dataset(tmp_path)
    reporter = _CaptureReporter()

    summary = run_workflow(
        root_path=paths["root_path"],
        annotation_file_path=paths["annotation_file"],
        captions_dir=paths["captions_dir"],
        output_dir=paths["output_dir"],
        memory_dir=paths["memory_dir"],
        gpu_device="0",
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
    workflow_summary = json.loads(workflow_summary_path.read_text(encoding="utf-8"))
    assert comparison["status"] == "ok"
    assert "roc_auc" in comparison["diff"]
    assert summary["compare"]["comparison_path"] == str(comparison_path)
    assert workflow_summary["config"]["use_vlm"] is False
    assert workflow_summary["config"]["vlm_mode"] == "caption"
    assert workflow_summary["config"]["gpu_device"] == "0"
    assert any(event.stage == "workflow" for event in reporter.events)


def test_compare_metric_reports_handles_missing_baseline():
    report = compare_metric_reports({"roc_auc": 0.9, "pr_auc": 0.8}, None)
    assert report["status"] == "baseline_unavailable"
    assert report["diff"]["roc_auc"]["delta"] is None
