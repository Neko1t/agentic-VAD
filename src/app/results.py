from __future__ import annotations

import json
from pathlib import Path

from src.app.models import ResultSummary


def load_results(run_root: Path) -> ResultSummary:
    workflow_summary_path = run_root / "workflow_summary.json"
    comparison_report_path = run_root / "comparison_report.json"

    workflow_summary = None
    comparison_report = None
    if workflow_summary_path.exists():
        workflow_summary = json.loads(workflow_summary_path.read_text(encoding="utf-8"))
    if comparison_report_path.exists():
        comparison_report = json.loads(comparison_report_path.read_text(encoding="utf-8"))

    return ResultSummary(
        run_root=run_root,
        workflow_summary_path=workflow_summary_path if workflow_summary_path.exists() else None,
        comparison_report_path=comparison_report_path if comparison_report_path.exists() else None,
        workflow_summary=workflow_summary,
        comparison_report=comparison_report,
    )
