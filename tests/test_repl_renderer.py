from __future__ import annotations

from pathlib import Path
from src.app.models import CheckStatus, ProjectStatusSnapshot, ResultSummary


def test_build_repl_overview_recommends_download_when_models_missing(tmp_path: Path):
    from src.app.status import build_repl_overview

    overview = build_repl_overview(repo_root=tmp_path, preferred_dataset="ucf_crime")

    assert overview["mini_ready"] is False
    assert any("assets download --preset models-core" in item for item in overview["recommended_commands"])


def test_build_repl_overview_recommends_run_mini_when_mini_dataset_is_ready(tmp_path: Path):
    from src.app.status import build_repl_overview

    mini_root = tmp_path / "data" / "ucf_crime_mini"
    (mini_root / "frames").mkdir(parents=True)
    (mini_root / "annotations").mkdir(parents=True)
    (mini_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (mini_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (mini_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )
    asset_root = tmp_path / ".asset_status"
    asset_root.mkdir(parents=True)
    (asset_root / "bge-base-en-v1.5.done").write_text("ok\n", encoding="utf-8")

    overview = build_repl_overview(repo_root=tmp_path, preferred_dataset="ucf_crime")

    assert overview["mini_ready"] is True
    assert "run mini" in overview["recommended_commands"]


def test_render_repl_overview_includes_sections_and_recent_results(tmp_path: Path):
    from src.app.repl_renderer import render_repl_overview
    from src.app.status import build_repl_overview

    output_root = tmp_path / "data" / "agentic_outputs" / "ucf_crime_mini"
    output_root.mkdir(parents=True)
    (output_root / "comparison_report.json").write_text(
        '{"status":"ok","diff":{"roc_auc":{"delta":0.12},"pr_auc":{"delta":-0.03}}}',
        encoding="utf-8",
    )

    overview = build_repl_overview(repo_root=tmp_path, preferred_dataset="ucf_crime")
    rendered = render_repl_overview(overview)

    assert "Agentic VAD Console" in rendered
    assert "Next Actions" in rendered
    assert "Environment" in rendered
    assert "Models" in rendered
    assert "Datasets" in rendered
    assert "Outputs" in rendered
    assert "Recent Results" in rendered


def test_render_doctor_summary_uses_grouped_sections(tmp_path: Path):
    from src.app.repl_renderer import render_doctor_summary

    snapshot = ProjectStatusSnapshot(
        ready=False,
        checks=[
            CheckStatus(name="python", ready=True, level="ok", message="python=3.10.20"),
            CheckStatus(name="conda_env", ready=True, level="ok", message="VAA"),
            CheckStatus(name="frames_root", ready=False, level="error", message="missing directory"),
            CheckStatus(name="annotation_file", ready=True, level="ok", message="file exists"),
            CheckStatus(name="output_dir", ready=True, level="ok", message="output directory will be created if missing"),
        ],
        root_path=tmp_path / "frames",
        annotation_file_path=tmp_path / "annotations" / "test.txt",
        captions_dir=tmp_path / "captions",
        output_dir=tmp_path / "outputs",
    )

    rendered = render_doctor_summary(snapshot)

    assert "Doctor Summary" in rendered
    assert "Runtime" in rendered
    assert "Dataset Inputs" in rendered
    assert "Outputs" in rendered


def test_render_compare_summary_uses_metric_labels(tmp_path: Path):
    from src.app.repl_renderer import render_compare_summary

    summary = ResultSummary(
        run_root=tmp_path,
        comparison_report={
            "status": "ok",
            "diff": {
                "roc_auc": {"delta": 0.12},
                "pr_auc": {"delta": -0.03},
            },
        },
    )

    rendered = render_compare_summary(summary)

    assert "Compare Summary" in rendered
    assert "ROC AUC" in rendered
    assert "PR AUC" in rendered


def test_render_result_summary_uses_compact_sections(tmp_path: Path):
    from src.app.repl_renderer import render_result_summary

    summary = ResultSummary(
        run_root=tmp_path,
        workflow_summary_path=tmp_path / "workflow_summary.json",
        comparison_report_path=tmp_path / "comparison_report.json",
        comparison_report={"status": "ok"},
    )

    rendered = render_result_summary(summary)

    assert "Result Summary" in rendered
    assert "Artifacts" in rendered
    assert "workflow summary" in rendered.lower()
    assert "comparison report" in rendered.lower()
