from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner


def test_root_entrypoint_module_exposes_cli_app():
    import agentic_vad

    assert hasattr(agentic_vad, "app")


def test_root_callback_launches_repl_when_no_subcommand(monkeypatch):
    from src.app.cli import app

    runner = CliRunner()
    called: dict[str, object] = {}

    def _run_repl_session(*, repo_root, preferred_dataset="ucf_crime", emit_output=print):
        called["repo_root"] = repo_root
        called["preferred_dataset"] = preferred_dataset
        return 0

    monkeypatch.setattr("src.app.cli.run_repl_session", _run_repl_session)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert called["preferred_dataset"] == "ucf_crime"


def test_doctor_command_reports_missing_assets(tmp_path: Path):
    from src.app.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "doctor",
            "--root-path",
            str(tmp_path / "data" / "ucf_crime" / "frames"),
            "--annotation-file-path",
            str(tmp_path / "data" / "ucf_crime" / "annotations" / "test.txt"),
            "--captions-dir",
            str(tmp_path / "data" / "ucf_crime" / "captions" / "video_llama3_json_results"),
            "--temporal-annotation-file",
            str(tmp_path / "data" / "ucf_crime" / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt"),
            "--baseline-scores-dir",
            str(tmp_path / "data" / "ucf_crime" / "refined_scores" / "videollama3"),
            "--output-dir",
            str(tmp_path / "data" / "agentic_outputs"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert any(item["level"] == "error" for item in payload["checks"])


def test_run_mini_command_routes_to_workflow(tmp_path: Path):
    from src.app.cli import app

    runner = CliRunner()
    data_root = tmp_path / "data" / "ucf_crime_mini"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "refined_scores" / "videollama3").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    (data_root / "captions" / "video_llama3_json_results" / "video_1.json").write_text(
        json.dumps(
            {
                "0": "A person walks on a street.",
                "16": "A person runs and falls on a street.",
            }
        ),
        encoding="utf-8",
    )
    (data_root / "refined_scores" / "videollama3" / "video_1.json").write_text(
        json.dumps({"0": 0.15, "16": 0.85}, indent=2),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "run",
            "mini",
            "--root-path",
            str(data_root / "frames"),
            "--annotation-file-path",
            str(data_root / "annotations" / "test.txt"),
            "--captions-dir",
            str(data_root / "captions" / "video_llama3_json_results"),
            "--temporal-annotation-file",
            str(data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt"),
            "--baseline-scores-dir",
            str(data_root / "refined_scores" / "videollama3"),
            "--output-dir",
            str(tmp_path / "outputs"),
            "--memory-dir",
            str(tmp_path / "memory"),
            "--no-use-chroma",
            "--gpu-device",
            "0",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["selected_stages"]
    assert payload["workflow_type"] == "mini"


def test_run_mini_command_requires_gpu_device(tmp_path: Path):
    from src.app.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "mini",
            "--root-path",
            str(tmp_path / "frames"),
            "--annotation-file-path",
            str(tmp_path / "annotations" / "test.txt"),
            "--captions-dir",
            str(tmp_path / "captions"),
            "--output-dir",
            str(tmp_path / "outputs"),
            "--memory-dir",
            str(tmp_path / "memory"),
        ],
    )

    assert result.exit_code != 0
    assert "--gpu-device" in result.stdout


def test_run_mini_command_accepts_vlm_options(monkeypatch, tmp_path: Path):
    from src.app.cli import app

    runner = CliRunner()
    captured: dict[str, object] = {}

    def _fake_run(request, *, capture_progress=False, monitor=None):
        captured["use_vlm"] = request.use_vlm
        captured["video_root_path"] = request.video_root_path
        captured["vlm_model_path"] = request.vlm_model_path
        captured["gpu_device"] = request.gpu_device
        return {"selected_stages": ["pipeline"], "workflow_type": "mini"}

    monkeypatch.setattr("src.app.cli.orchestrator.run", _fake_run)

    result = runner.invoke(
        app,
        [
            "run",
            "mini",
            "--root-path",
            str(tmp_path / "frames"),
            "--annotation-file-path",
            str(tmp_path / "annotations" / "test.txt"),
            "--captions-dir",
            str(tmp_path / "captions"),
            "--output-dir",
            str(tmp_path / "outputs"),
            "--memory-dir",
            str(tmp_path / "memory"),
            "--gpu-device",
            "1",
            "--use-vlm",
            "--video-root-path",
            str(tmp_path / "videos"),
            "--vlm-model-path",
            str(tmp_path / "models" / "VideoLLaMA3-7B"),
        ],
    )

    assert result.exit_code == 0
    assert captured["use_vlm"] is True
    assert captured["gpu_device"] == "1"
    assert str(captured["video_root_path"]).endswith("videos")
    assert str(captured["vlm_model_path"]).endswith("VideoLLaMA3-7B")
