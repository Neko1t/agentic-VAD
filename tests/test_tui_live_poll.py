from __future__ import annotations

from pathlib import Path

from src.runtime.progress import ProgressEvent


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


def test_poll_live_progress_updates_sections_from_monitor(tmp_path: Path):
    from src.app.run_monitor import WorkflowMonitor
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")
    monitor = WorkflowMonitor()
    monitor.consume(
        ProgressEvent(
            stage="pipeline",
            event="window_end",
            message="processed",
            completed=3,
            total=5,
            tool_name="vlm_describe",
        )
    )
    app.active_monitor = monitor

    app.poll_live_progress()

    assert "pipeline" in app.sections["live_progress"]
    assert "3/5" in app.sections["live_progress"]
