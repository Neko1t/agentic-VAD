from __future__ import annotations

from pathlib import Path


def _prepare_app_root(tmp_path: Path) -> Path:
    for dataset_name in ("ucf_crime", "ucf_crime_mini"):
        data_root = tmp_path / "data" / dataset_name
        (data_root / "frames").mkdir(parents=True)
        (data_root / "annotations").mkdir(parents=True)
        (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
        (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
        (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
            "video_1.mp4 0 0 31\n",
            encoding="utf-8",
        )
    return tmp_path


def test_run_default_workflow_passes_active_monitor_to_orchestrator(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    captured = {}

    def _run(request, *, capture_progress: bool = False, monitor=None):
        captured["capture_progress"] = capture_progress
        captured["monitor"] = monitor
        return {
            "workflow_type": request.workflow_type.value,
            "progress": {"latest": {"stage": "compare", "message": "done"}, "stages": {}},
            "compare": {"status": "ok"},
            "workflow_summary_path": str(tmp_path / "data" / "agentic_outputs" / "ucf_crime_mini" / "workflow_summary.json"),
        }

    monkeypatch.setattr("src.app.tui_app.orchestrator.run", _run)

    app.run_default_workflow("mini")

    assert captured["capture_progress"] is True
    assert captured["monitor"] is not None
