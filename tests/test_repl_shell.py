from __future__ import annotations

from pathlib import Path
import time


def test_run_repl_session_renders_overview_and_help(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    inputs = iter(["help", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "Agentic VAD Console" in combined
    assert "Supported Commands" in combined
    assert "set vlm on" in combined
    assert "set gpu 0" in combined or "set gpu <id>" in combined.lower()


def test_run_repl_session_reports_unknown_command(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    inputs = iter(["fly away", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert "unknown command" in "\n".join(outputs).lower()


def test_run_repl_session_supports_status_and_results(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    output_root = tmp_path / "data" / "agentic_outputs"
    output_root.mkdir(parents=True)

    inputs = iter(["status", "results", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "Agentic VAD Console" in combined
    assert "Next Actions" in combined
    assert "Result Summary" in combined


def test_run_repl_session_supports_doctor(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )

    inputs = iter(["doctor", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "Doctor Summary" in combined
    assert "annotation_file" in combined


def test_run_repl_session_blocks_run_mini_when_dataset_missing(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    inputs = iter(["run mini", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert "mini dataset is not ready" in "\n".join(outputs).lower()


def test_run_repl_session_runs_mini_when_ready(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "videos").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "refined_scores" / "videollama3").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    asset_root = tmp_path / ".asset_status"
    asset_root.mkdir(parents=True)
    (asset_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")

    recorded: dict[str, object] = {}

    def _fake_run(request, *, capture_progress=False, monitor=None):
        recorded["workflow_type"] = request.workflow_type.value
        recorded["capture_progress"] = capture_progress
        recorded["use_vlm"] = request.use_vlm
        recorded["gpu_device"] = request.gpu_device
        return {
            "workflow_type": "mini",
            "resolved_stages": ["pipeline", "metrics", "compare"],
            "progress": {"latest": {"stage": "compare", "message": "done"}, "stages": {"pipeline": {"completed": 1, "total": 1}}},
            "compare": {"status": "ok", "diff": {"roc_auc": {"delta": 0.2}, "pr_auc": {"delta": -0.1}}},
            "workflow_summary_path": str(tmp_path / "data" / "agentic_outputs" / "ucf_crime_mini" / "workflow_summary.json"),
        }

    inputs = iter(["set gpu 0", "run mini", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("src.app.repl_shell.orchestrator.run", _fake_run)
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert recorded["workflow_type"] == "mini"
    assert recorded["capture_progress"] is True
    assert recorded["use_vlm"] is False
    assert recorded["gpu_device"] == "0"
    combined = "\n".join(outputs)
    assert "Run" in combined
    assert "Status" in combined
    assert "compare" in combined.lower()


def test_run_repl_session_blocks_run_when_gpu_unset(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "videos").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "refined_scores" / "videollama3").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    asset_root = tmp_path / ".asset_status"
    asset_root.mkdir(parents=True)
    (asset_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")

    outputs: list[str] = []
    inputs = iter(["run mini", "exit"])

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert "set gpu" in "\n".join(outputs).lower()


def test_run_repl_session_applies_vlm_session_setting(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "videos").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "refined_scores" / "videollama3").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    asset_root = tmp_path / ".asset_status"
    asset_root.mkdir(parents=True)
    (asset_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run(request, *, capture_progress=False, monitor=None):
        captured["use_vlm"] = request.use_vlm
        captured["video_root_path"] = request.video_root_path
        captured["vlm_model_path"] = request.vlm_model_path
        captured["gpu_device"] = request.gpu_device
        return {
            "workflow_type": "mini",
            "resolved_stages": ["pipeline"],
            "progress": monitor.snapshot() if monitor is not None else {},
            "compare": {"status": "missing"},
        }

    inputs = iter(["set gpu 1", "set vlm on", "run mini", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("src.app.repl_shell.orchestrator.run", _fake_run)
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert captured["use_vlm"] is True
    assert str(captured["video_root_path"]).endswith("videos")
    assert str(captured["vlm_model_path"]).endswith("VideoLLaMA3-7B")
    assert captured["gpu_device"] == "1"
    assert "vlm mode is now on" in "\n".join(outputs).lower()


def test_run_repl_session_streams_progress_updates(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session
    from src.runtime.progress import ProgressEvent

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "refined_scores" / "videollama3").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    asset_root = tmp_path / ".asset_status"
    asset_root.mkdir(parents=True)
    (asset_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")

    def _fake_run(request, *, capture_progress=False, monitor=None):
        assert capture_progress is True
        assert monitor is not None
        monitor.consume(
            ProgressEvent(
                stage="pipeline",
                event="window_done",
                message="caption scoring",
                completed=1,
                total=3,
                tool_name="vlm_tool",
            )
        )
        time.sleep(0.1)
        monitor.consume(
            ProgressEvent(
                stage="compare",
                event="complete",
                message="comparison finished",
                completed=3,
                total=3,
            )
        )
        return {
            "workflow_type": "mini",
            "resolved_stages": ["pipeline", "metrics", "compare"],
            "progress": monitor.snapshot(),
            "compare": {"status": "ok"},
        }

    inputs = iter(["set gpu 0", "run mini", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("src.app.repl_shell.orchestrator.run", _fake_run)
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "Active" in combined
    assert "Stage Progress" in combined
    assert "Recent Events" in combined
    assert "vlm_tool" in combined
    assert "comparison finished" in combined


def test_run_repl_session_supports_download_and_build_hints(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    inputs = iter(["download models-core", "build mini", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "download_agentic_assets.py" in combined
    assert "--preset models-core" in combined
    assert "build_ucf_crime_mini_subset.py" in combined


def test_run_repl_session_supports_compare(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    output_root = tmp_path / "data" / "agentic_outputs"
    output_root.mkdir(parents=True)
    (output_root / "comparison_report.json").write_text(
        '{"status":"ok","diff":{"roc_auc":{"delta":0.12},"pr_auc":{"delta":-0.03}}}',
        encoding="utf-8",
    )

    inputs = iter(["compare", "exit"])
    outputs: list[str] = []

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    combined = "\n".join(outputs)
    assert "Compare Summary" in combined
    assert "roc_auc_delta" in combined


def test_run_repl_session_uses_contextual_prompt(monkeypatch, tmp_path: Path):
    from src.app.repl_shell import run_repl_session

    inputs = iter(["exit"])
    prompts: list[str] = []
    outputs: list[str] = []

    def _fake_input(prompt=""):
        prompts.append(prompt)
        return next(inputs)

    monkeypatch.setattr("builtins.input", _fake_input)
    exit_code = run_repl_session(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
        emit_output=outputs.append,
    )

    assert exit_code == 0
    assert prompts[0].startswith("agentic-vad [")
    assert "mini:" in prompts[0]
    assert "full:" in prompts[0]
    assert "vlm:" in prompts[0]
    assert "gpu:" in prompts[0]
