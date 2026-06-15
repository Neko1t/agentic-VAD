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


def test_start_background_run_uses_thread_factory_and_marks_running(tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")

    recorded = {}

    class _FakeThread:
        def __init__(self, target, name: str, daemon: bool):
            recorded["target"] = target
            recorded["name"] = name
            recorded["daemon"] = daemon
            self.started = False

        def start(self):
            self.started = True
            recorded["started"] = True

    app.thread_factory = lambda target, name, daemon: _FakeThread(target, name, daemon)

    result = app.start_background_run("mini")

    assert result is None
    assert app.run_active is True
    assert recorded["name"] == "agentic-vad-mini"
    assert recorded["daemon"] is True
    assert recorded["started"] is True


def test_complete_background_run_clears_running_and_updates_sections(tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    app._is_running = True

    summary = {
        "workflow_type": "mini",
        "progress": {
            "latest": {"stage": "compare", "message": "status=ok", "tool_name": None},
            "stages": {"pipeline": {"completed": 2, "total": 2}},
        },
        "compare": {"status": "ok"},
        "workflow_summary_path": str(tmp_path / "data" / "agentic_outputs" / "ucf_crime_mini" / "workflow_summary.json"),
    }

    app.complete_background_run(summary)

    assert app.run_active is False
    assert "status=ok" in app.sections["live_progress"]


def test_fail_background_run_clears_running_and_records_error(tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    app._is_running = True

    app.fail_background_run(RuntimeError("boom"))

    assert app.run_active is False
    assert "boom" in app.sections["live_progress"]
