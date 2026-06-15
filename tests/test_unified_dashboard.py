from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.app.models import ProjectStatusSnapshot


def test_default_entrypoint_without_args_shows_dashboard():
    import agentic_vad

    runner = CliRunner()
    result = runner.invoke(agentic_vad.app, [])

    assert result.exit_code == 0
    assert "Agentic VAD" in result.stdout
    assert "Project Status" in result.stdout
    assert "Suggested Commands" in result.stdout
    assert result.stdout.count("Project Status") == 1


def test_help_does_not_render_dashboard():
    import agentic_vad

    runner = CliRunner()
    result = runner.invoke(agentic_vad.app, ["doctor", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "Project Status" not in result.stdout


def test_dashboard_snapshot_detects_mini_and_full_readiness(tmp_path: Path):
    from src.app.status import build_workspace_snapshot

    data_root = tmp_path / "data"
    mini_root = data_root / "ucf_crime_mini"
    full_root = data_root / "ucf_crime"
    asset_status_root = tmp_path / ".asset_status"
    outputs_root = data_root / "agentic_outputs" / "ucf_crime_mini" / "latest"
    asset_status_root.mkdir(parents=True)
    outputs_root.mkdir(parents=True)
    (asset_status_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")
    (outputs_root / "comparison_report.json").write_text(
        '{"status":"ok","diff":{"roc_auc":{"delta":0.1},"pr_auc":{"delta":-0.02}}}',
        encoding="utf-8",
    )
    (outputs_root / "workflow_summary.json").write_text(
        '{"selected_stages":["pipeline","metrics","compare"]}',
        encoding="utf-8",
    )

    for base in (mini_root, full_root):
        (base / "frames").mkdir(parents=True)
        (base / "annotations").mkdir(parents=True)
        (base / "captions" / "video_llama3_json_results").mkdir(parents=True)
        (base / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
        (base / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
            "video_1.mp4 0 0 31\n",
            encoding="utf-8",
        )

    snapshot = build_workspace_snapshot(
        repo_root=tmp_path,
        preferred_dataset="ucf_crime",
    )

    assert snapshot["mini_ready"] is True
    assert snapshot["full_ready"] is True
    assert "models" in snapshot
    assert "datasets" in snapshot
    assert snapshot["models"][0]["ready"] is True
    assert snapshot["recent_result"] is not None


def test_render_dashboard_contains_required_sections():
    from src.app.dashboard import render_dashboard

    snapshot = ProjectStatusSnapshot(
        ready=False,
        checks=[],
        root_path=Path("./data/ucf_crime/frames"),
        annotation_file_path=Path("./data/ucf_crime/annotations/test.txt"),
        captions_dir=Path("./data/ucf_crime/captions/video_llama3_json_results"),
    )
    workspace = {
        "preferred_dataset": "ucf_crime",
        "mini_ready": False,
        "full_ready": True,
        "models": [],
        "datasets": [],
        "required_actions": ["download models", "prepare mini dataset"],
        "recent_result": {"status": "ok", "summary": "mini experiment available"},
    }

    rendered = render_dashboard(snapshot=snapshot, workspace=workspace)

    assert "Project Status" in rendered
    assert "Dataset Readiness" in rendered
    assert "Recent Results" in rendered
    assert "Required Actions" in rendered
    assert "Suggested Commands" in rendered
