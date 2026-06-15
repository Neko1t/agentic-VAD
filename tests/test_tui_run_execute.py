from __future__ import annotations

from pathlib import Path


def test_run_default_workflow_applies_orchestrator_summary(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    data_root = tmp_path / "data" / "ucf_crime"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )

    captured = {}

    def _run(request, *, capture_progress: bool = False, monitor=None):
        captured["workflow_type"] = request.workflow_type.value
        captured["capture_progress"] = capture_progress
        captured["monitor"] = monitor
        return {
            "workflow_type": request.workflow_type.value,
            "progress": {"latest": {"stage": "compare", "message": "status=ok", "tool_name": None}, "stages": {}},
            "compare": {"status": "ok"},
            "workflow_summary_path": str(tmp_path / "data" / "agentic_outputs" / "ucf_crime_mini" / "workflow_summary.json"),
        }

    monkeypatch.setattr("src.app.tui_app.orchestrator.run", _run)

    app = AgenticVADApp(repo_root=tmp_path, preferred_dataset="ucf_crime")
    summary = app.run_default_workflow("mini")

    assert captured["workflow_type"] == "mini"
    assert captured["capture_progress"] is True
    assert captured["monitor"] is not None
    assert summary["compare"]["status"] == "ok"
    assert "status=ok" in app.sections["live_progress"]
