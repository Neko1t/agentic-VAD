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


def test_on_mount_registers_interval_when_textual_available(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    repo_root = _prepare_app_root(tmp_path)
    recorded = {}

    def _set_interval(interval: float, callback):
        recorded["interval"] = interval
        recorded["callback"] = callback
        return None

    monkeypatch.setattr("src.app.tui_app.TEXTUAL_AVAILABLE", True)
    monkeypatch.setattr(AgenticVADApp, "set_interval", lambda self, interval, callback: _set_interval(interval, callback), raising=False)

    app = AgenticVADApp(repo_root=repo_root, preferred_dataset="ucf_crime")

    app.on_mount()

    assert recorded["interval"] == 0.5
    assert recorded["callback"] == app.refresh_live_sections
