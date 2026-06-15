from __future__ import annotations

from io import StringIO
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.table import Table
from src.app.models import ProjectStatusSnapshot
from src.app.models import ResultSummary


def render_repl_overview(overview: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())

    recent_result = overview.get("recent_result") or {}
    last_status = recent_result.get("status") or "none"
    mini_state = "ready" if overview.get("mini_ready") else "missing"
    full_state = "ready" if overview.get("full_ready") else "missing"
    console.print(
        Panel(
            f"REPL   mini: {mini_state}   full: {full_state}   last: {last_status}",
            title="Agentic VAD Console",
            box=box.SIMPLE,
        )
    )

    environment_panel = Panel(
        "Environment\n"
        "python: detected\n"
        "conda: detected\n"
        "rich: enabled",
        box=box.SIMPLE,
    )
    models = overview.get("models", [])
    model_lines = ["Models"]
    for item in models:
        model_lines.append(f"{item.get('name')}: {'ok' if item.get('ready') else 'missing'}")
    models_panel = Panel("\n".join(model_lines), box=box.SIMPLE)

    datasets = overview.get("datasets", [])
    dataset_lines = ["Datasets"]
    for item in datasets:
        dataset_lines.append(f"{item.get('name')}: {'ready' if item.get('ready') else 'missing'}")
    datasets_panel = Panel("\n".join(dataset_lines), box=box.SIMPLE)

    outputs_lines = [
        "Outputs",
        f"recent: {last_status}",
        "comparison: present" if recent_result else "comparison: missing",
        "reports: available" if recent_result else "reports: missing",
    ]
    outputs_panel = Panel("\n".join(outputs_lines), box=box.SIMPLE)
    console.print(Columns([environment_panel, models_panel, datasets_panel, outputs_panel], expand=True))

    console.print("Next Actions")
    action_lines: list[str] = []
    recommended_commands = list(overview.get("recommended_commands", []))
    reasons = {
        "run mini": "Mini experiment can be launched with the current setup.",
        "run full": "Full experiment can be launched with the current setup.",
    }
    for index, item in enumerate(recommended_commands, start=1):
        action_lines.append(f"{index}. {item}")
        reason = reasons.get(item)
        if reason is None:
            if "assets download" in item:
                reason = "Missing required model assets."
            elif "dataset build-mini" in item:
                reason = "Mini dataset is not ready for smoke experiments."
            else:
                reason = "Recommended next step from the current workspace state."
        action_lines.append(f"   {reason}")
    if not action_lines:
        action_lines.append("1. help")
        action_lines.append("   Explore the supported command surface.")
    console.print(Panel("\n".join(action_lines), box=box.SIMPLE))

    console.print("Recent Results")
    result_table = Table(show_lines=True, box=box.SIMPLE)
    result_table.add_column("Field")
    result_table.add_column("Value")
    if recent_result:
        result_table.add_row("status", str(recent_result.get("status")))
        result_table.add_row("summary", str(recent_result.get("summary")))
        comparison = recent_result.get("comparison") or {}
        diff = comparison.get("diff") or {}
        for metric_name in ("roc_auc", "pr_auc"):
            metric_payload = diff.get(metric_name)
            if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
                result_table.add_row(f"{metric_name}_delta", f"{float(metric_payload['delta']):.4f}")
    else:
        result_table.add_row("status", "no persisted comparison report found")
    console.print(result_table)
    console.print("Try: help | doctor | run mini | compare")

    return console.export_text(styles=False)


def render_result_summary(summary: ResultSummary) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Result Summary")
    status_table = Table(show_lines=True, box=box.SIMPLE)
    status_table.add_column("Field")
    status_table.add_column("Value")
    status_table.add_row("run root", str(summary.run_root))
    if summary.comparison_report:
        status_table.add_row("status", str(summary.comparison_report.get("status")))
    console.print(status_table)

    console.print("Artifacts")
    artifact_table = Table(show_lines=True, box=box.SIMPLE)
    artifact_table.add_column("Artifact")
    artifact_table.add_column("Present")
    artifact_table.add_row("workflow summary", "yes" if summary.workflow_summary_path else "no")
    artifact_table.add_row("comparison report", "yes" if summary.comparison_report_path else "no")
    console.print(artifact_table)
    return console.export_text(styles=False)


def render_doctor_summary(snapshot: ProjectStatusSnapshot) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Doctor Summary")

    groups = {
        "Runtime": {"python", "conda_env", "typer", "rich"},
        "Dataset Inputs": {"frames_root", "annotation_file", "captions_dir", "temporal_annotation_file"},
        "Outputs": {"baseline_scores_dir", "output_dir"},
    }
    for title, names in groups.items():
        console.print(title)
        table = Table(show_lines=True, box=box.SIMPLE)
        table.add_column("Check")
        table.add_column("Level")
        table.add_column("Message")
        for check in snapshot.checks:
            if check.name in names:
                table.add_row(check.name, check.level, check.message)
        if table.row_count > 0:
            console.print(table)
    return console.export_text(styles=False)


def render_run_summary(summary: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    workflow_type = str(summary.get("workflow_type"))
    resolved_stages = " -> ".join(summary.get("resolved_stages", []))
    console.print(f"Run   workflow: {workflow_type}   Status: done")

    summary_table = Table(show_lines=True, box=box.SIMPLE)
    summary_table.add_column("Field")
    summary_table.add_column("Value")
    summary_table.add_row("Stages", resolved_stages)
    compare = summary.get("compare") or {}
    summary_table.add_row("Compare Status", str(compare.get("status") or "missing"))
    console.print(summary_table)

    diff = compare.get("diff") or {}
    if diff:
        console.print("Metrics")
        metrics_table = Table(show_lines=True, box=box.SIMPLE)
        metrics_table.add_column("Metric")
        metrics_table.add_column("Delta")
        metric_labels = {"roc_auc": "ROC AUC", "pr_auc": "PR AUC"}
        for metric_name in ("roc_auc", "pr_auc"):
            metric_payload = diff.get(metric_name)
            if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
                metrics_table.add_row(metric_labels[metric_name], f"{float(metric_payload['delta']):+.4f}")
        if metrics_table.row_count > 0:
            console.print(metrics_table)

    workflow_summary_path = summary.get("workflow_summary_path")
    if workflow_summary_path:
        console.print("Artifacts")
        artifact_table = Table(show_lines=True, box=box.SIMPLE)
        artifact_table.add_column("Artifact")
        artifact_table.add_column("Present")
        artifact_table.add_row("workflow summary", "yes")
        artifact_table.add_row("comparison report", "yes" if compare else "no")
        console.print(artifact_table)
    return console.export_text(styles=False)


def render_progress_snapshot(progress: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    latest = (progress or {}).get("latest") or {}
    latest_stage = str(latest.get("stage") or "unknown")
    console.print(f"Run   Status: running   Stage: {latest_stage}")
    console.print("Active")
    active_table = Table(show_lines=True, box=box.SIMPLE)
    active_table.add_column("Field")
    active_table.add_column("Value")
    if latest:
        active_table.add_row("stage", str(latest.get("stage")))
        active_table.add_row("tool", str(latest.get("tool_name") or latest.get("event")))
        active_table.add_row("message", str(latest.get("message")))
    if active_table.row_count > 0:
        console.print(active_table)

    console.print("Stage Progress")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Stage")
    table.add_column("Progress")
    stages = (progress or {}).get("stages") or {}
    for stage_name, state in stages.items():
        completed = state.get("completed")
        total = state.get("total")
        if completed is not None and total is not None:
            table.add_row(stage_name, f"{completed}/{total}")
        else:
            table.add_row(stage_name, "active")

    if table.row_count > 0:
        console.print(table)
    events = (progress or {}).get("events") or []
    if events:
        console.print("Recent Events")
        events_table = Table(show_lines=True, box=box.SIMPLE)
        events_table.add_column("Stage")
        events_table.add_column("Tool/Event")
        events_table.add_column("Message")
        for event in events[-5:]:
            events_table.add_row(
                str(event.get("stage")),
                str(event.get("tool_name") or event.get("event")),
                str(event.get("message")),
            )
        console.print(events_table)
    return console.export_text(styles=False)


def render_compare_summary(summary: ResultSummary) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Compare Summary")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Field")
    table.add_column("Value")

    comparison = summary.comparison_report or {}
    table.add_row("status", str(comparison.get("status") or "missing"))
    diff = comparison.get("diff") or {}
    metric_labels = {"roc_auc": "ROC AUC", "pr_auc": "PR AUC"}
    for metric_name in ("roc_auc", "pr_auc"):
        metric_payload = diff.get(metric_name)
        if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
            table.add_row(metric_labels[metric_name], f"{float(metric_payload['delta']):+.4f}")

    console.print(table)
    return console.export_text(styles=False)
