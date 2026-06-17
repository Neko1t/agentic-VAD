from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_build_default_run_request_for_mini_dataset(monkeypatch, tmp_path: Path):
    from src.app.tui_app import build_default_run_request

    monkeypatch.setenv("GPU_DEVICE", "1")
    repo_root = tmp_path
    request = build_default_run_request(repo_root=repo_root, preferred_dataset="ucf_crime", workflow_kind="mini")

    assert request.workflow_type.value == "mini"
    assert request.gpu_device == "1"
    assert str(request.root_path).endswith("data\\ucf_crime_mini\\frames") or str(request.root_path).endswith("data/ucf_crime_mini/frames")


def test_build_default_run_request_requires_gpu_device_env(monkeypatch, tmp_path: Path):
    from src.app.tui_app import build_default_run_request

    monkeypatch.delenv("GPU_DEVICE", raising=False)

    with pytest.raises(ValueError, match="GPU_DEVICE"):
        build_default_run_request(repo_root=tmp_path, preferred_dataset="ucf_crime", workflow_kind="mini")


def test_apply_run_summary_updates_live_progress_and_recent_results(tmp_path: Path):
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

    app = AgenticVADApp(repo_root=tmp_path, preferred_dataset="ucf_crime")
    summary = {
        "progress": {
            "latest": {"stage": "compare", "message": "status=ok", "tool_name": None},
            "stages": {"pipeline": {"completed": 2, "total": 2}},
        },
        "compare": {"status": "ok"},
        "workflow_summary_path": str(tmp_path / "data" / "agentic_outputs" / "workflow_summary.json"),
    }

    app.apply_run_summary(summary)

    assert "compare" in app.sections["live_progress"]
    assert "status=ok" in app.sections["live_progress"]
