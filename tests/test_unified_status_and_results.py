from __future__ import annotations

import json
from pathlib import Path

from src.app.results import load_results
from src.app.status import build_status_snapshot


def test_status_snapshot_marks_ready_when_required_paths_exist(tmp_path: Path):
    root_path = tmp_path / "frames"
    captions_dir = tmp_path / "captions"
    annotations_dir = tmp_path / "annotations"
    root_path.mkdir()
    captions_dir.mkdir()
    annotations_dir.mkdir()
    annotation_file = annotations_dir / "test.txt"
    temporal_file = annotations_dir / "temporal.txt"
    annotation_file.write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    temporal_file.write_text("video_1.mp4 0 0 31\n", encoding="utf-8")

    snapshot = build_status_snapshot(
        root_path=root_path,
        annotation_file_path=annotation_file,
        captions_dir=captions_dir,
        temporal_annotation_file=temporal_file,
        output_dir=tmp_path / "outputs",
    )

    assert snapshot.ready is True
    assert all(check.level != "error" for check in snapshot.checks)


def test_load_results_reads_workflow_and_comparison_files(tmp_path: Path):
    run_root = tmp_path / "outputs"
    run_root.mkdir()
    workflow_summary = {"selected_stages": ["pipeline", "metrics"]}
    comparison_report = {"status": "ok", "diff": {"roc_auc": {"delta": 0.1}}}
    (run_root / "workflow_summary.json").write_text(json.dumps(workflow_summary), encoding="utf-8")
    (run_root / "comparison_report.json").write_text(json.dumps(comparison_report), encoding="utf-8")

    summary = load_results(run_root)

    assert summary.workflow_summary == workflow_summary
    assert summary.comparison_report == comparison_report
