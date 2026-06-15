from __future__ import annotations

from pathlib import Path


def _prepare_app_root(tmp_path: Path) -> Path:
    data_root = tmp_path / "data" / "ucf_crime"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    return tmp_path


def test_start_run_marks_live_progress_as_running(tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")

    app.mark_run_started("mini")

    assert "running mini workflow" in app.sections["live_progress"]


def test_start_background_run_uses_runner_callable(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")

    called = {}

    def _runner(workflow_kind: str):
        called["workflow_kind"] = workflow_kind
        return {"workflow_type": workflow_kind, "compare": {"status": "ok"}, "progress": {"latest": {"stage": "compare", "message": "done"}}}

    app.run_workflow_callable = _runner
    app.start_background_run("mini")

    assert called["workflow_kind"] == "mini"
    assert "done" in app.sections["live_progress"] or "compare" in app.sections["live_progress"]
