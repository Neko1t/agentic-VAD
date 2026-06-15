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
    )

    external_monitor = WorkflowMonitor()
    summary = orchestrator.run(request, capture_progress=True, monitor=external_monitor)

    assert "progress" in summary
    assert summary["progress"]["latest"]["stage"] in {"workflow", "compare", "metrics", "pipeline", "baseline_metrics"}
    assert external_monitor.snapshot()["latest"] is not None
