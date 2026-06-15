from __future__ import annotations

from pathlib import Path


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

    assert "Agentic VAD REPL" in rendered
    assert "Recommended Commands" in rendered
    assert "Recent Results" in rendered
