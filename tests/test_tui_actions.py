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


def test_action_run_mini_uses_mini_workflow(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    called = {}

    def _start_background_run(workflow_kind: str):
        called["workflow_kind"] = workflow_kind
        return {}

    monkeypatch.setattr(app, "start_background_run", _start_background_run)

    app.action_run_mini()

    assert called["workflow_kind"] == "mini"


def test_action_run_full_uses_full_workflow(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    called = {}

    def _start_background_run(workflow_kind: str):
        called["workflow_kind"] = workflow_kind
        return {}

    monkeypatch.setattr(app, "start_background_run", _start_background_run)

    app.action_run_full()

    assert called["workflow_kind"] == "full"
