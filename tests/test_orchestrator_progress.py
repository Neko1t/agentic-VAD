from __future__ import annotations

import json
from pathlib import Path

from src.app.models import RunRequest, WorkflowType
from src.core.schemas import RunMode


def test_orchestrator_run_can_return_progress_snapshot(tmp_path: Path):
    from src.app import orchestrator
    from src.app.run_monitor import WorkflowMonitor

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
        json.dumps({"0": "A person walks.", "16": "A person falls."}),
        encoding="utf-8",
    )
    baseline_scores_dir = tmp_path / "baseline_scores"
    baseline_scores_dir.mkdir()
    (baseline_scores_dir / "video_1.json").write_text(
        json.dumps({"0": 0.2, "16": 0.9}),
        encoding="utf-8",
    )

    request = RunRequest(
        workflow_type=WorkflowType.MINI,
        root_path=root_path,
        annotation_file_path=annotation_file,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        stage_names=["pipeline", "metrics", "baseline-metrics", "compare"],
        run_mode=RunMode.ONLINE_INFERENCE,
        use_chroma=False,
        gpu_device="0",
    )

    external_monitor = WorkflowMonitor()
    summary = orchestrator.run(request, capture_progress=True, monitor=external_monitor)

    assert "progress" in summary
    assert summary["progress"]["latest"]["stage"] in {"workflow", "compare", "metrics", "pipeline", "baseline_metrics"}
    assert external_monitor.snapshot()["latest"] is not None


def test_orchestrator_run_persists_request_to_workflow_summary(monkeypatch, tmp_path: Path):
    from src.app import orchestrator

    monkeypatch.setattr("src.runtime.device._list_gpu_indices", lambda: ["0", "1"])

    root_path = tmp_path / "dataset"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "outputs"
    memory_dir = tmp_path / "memory"
    video_root_path = tmp_path / "videos"
    vlm_model_path = tmp_path / "models" / "VideoLLaMA3-7B"
    root_path.mkdir()
    captions_dir.mkdir()
    video_root_path.mkdir(parents=True)
    vlm_model_path.mkdir(parents=True)
    annotation_file = tmp_path / "test.txt"
    temporal_annotation_file = tmp_path / "temporal.txt"
    annotation_file.write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    temporal_annotation_file.write_text("video_1.mp4 0 0 31\n", encoding="utf-8")
    (captions_dir / "video_1.json").write_text(
        json.dumps({"0": "A person walks.", "16": "A person falls."}),
        encoding="utf-8",
    )
    baseline_scores_dir = tmp_path / "baseline_scores"
    baseline_scores_dir.mkdir()
    (baseline_scores_dir / "video_1.json").write_text(
        json.dumps({"0": 0.2, "16": 0.9}),
        encoding="utf-8",
    )

    request = RunRequest(
        workflow_type=WorkflowType.MINI,
        root_path=root_path,
        annotation_file_path=annotation_file,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        stage_names=["pipeline", "metrics", "baseline-metrics", "compare"],
        run_mode=RunMode.ONLINE_INFERENCE,
        use_chroma=False,
        gpu_device="1",
        use_vlm=True,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )

    summary = orchestrator.run(request)

    workflow_summary_path = Path(summary["workflow_summary_path"])
    persisted = json.loads(workflow_summary_path.read_text(encoding="utf-8"))
    assert persisted["workflow_type"] == "mini"
    assert persisted["request"]["use_vlm"] is True
    assert persisted["request"]["gpu_device"] == "1"
    assert persisted["request"]["video_root_path"].endswith("videos")
    assert persisted["request"]["vlm_model_path"].endswith("VideoLLaMA3-7B")


def test_build_default_run_request_uses_mini_paths(tmp_path: Path):
    from src.app import orchestrator
    from src.app.models import WorkflowType

    request = orchestrator.build_default_run_request(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        workflow_type=WorkflowType.MINI,
    )

    assert request.workflow_type == WorkflowType.MINI
    assert str(request.root_path).endswith("data\\ucf_crime_mini\\frames") or str(request.root_path).endswith("data/ucf_crime_mini/frames")
    assert str(request.video_root_path).endswith("data\\ucf_crime_mini\\videos") or str(request.video_root_path).endswith("data/ucf_crime_mini/videos")


def test_build_default_run_request_uses_full_paths(tmp_path: Path):
    from src.app import orchestrator
    from src.app.models import WorkflowType

    request = orchestrator.build_default_run_request(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        workflow_type=WorkflowType.FULL,
    )

    assert request.workflow_type == WorkflowType.FULL
    assert str(request.root_path).endswith("data\\ucf_crime\\frames") or str(request.root_path).endswith("data/ucf_crime/frames")
    assert str(request.video_root_path).endswith("data\\ucf_crime\\videos") or str(request.video_root_path).endswith("data/ucf_crime/videos")
