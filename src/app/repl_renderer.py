from __future__ import annotations

from io import StringIO
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.app.models import ProjectStatusSnapshot
from src.app.models import ResultSummary


def render_repl_overview(overview: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())

    console.print(
        Panel(
            "Persistent command console for agentic VAD experiments.",
            title="Agentic VAD REPL",
            box=box.SQUARE,
        )
    )

    console.print("Workspace Readiness")
    status_table = Table(show_lines=True, box=box.SIMPLE)
    status_table.add_column("Item")
    status_table.add_column("Ready")
    status_table.add_row("mini", "yes" if overview.get("mini_ready") else "no")
    status_table.add_row("full", "yes" if overview.get("full_ready") else "no")
    console.print(status_table)

    console.print("Missing Items")
    missing_table = Table(show_lines=True, box=box.SIMPLE)
    missing_table.add_column("Item")
    missing_items = overview.get("missing_items") or ["none"]
    for item in missing_items:
        missing_table.add_row(str(item))
    console.print(missing_table)

    console.print("Recommended Commands")
    command_table = Table(show_lines=True, box=box.SIMPLE)
    command_table.add_column("Command")
    for item in overview.get("recommended_commands", []):
        command_table.add_row(str(item))
    console.print(command_table)

    console.print("Recent Results")
    result_table = Table(show_lines=True, box=box.SIMPLE)
    result_table.add_column("Field")
    result_table.add_column("Value")
    recent_result = overview.get("recent_result")
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

    return console.export_text(styles=False)


def render_result_summary(summary: ResultSummary) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Result Summary")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_root", str(summary.run_root))
    table.add_row("workflow_summary", "yes" if summary.workflow_summary_path else "no")
    table.add_row("comparison_report", "yes" if summary.comparison_report_path else "no")
    if summary.comparison_report:
        table.add_row("status", str(summary.comparison_report.get("status")))
    console.print(table)
    return console.export_text(styles=False)


def render_doctor_summary(snapshot: ProjectStatusSnapshot) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Doctor Summary")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Check")
    table.add_column("Level")
    table.add_column("Message")
    for check in snapshot.checks:
        table.add_row(check.name, check.level, check.message)
    console.print(table)
    return console.export_text(styles=False)


def render_run_summary(summary: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Run Summary")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("workflow_type", str(summary.get("workflow_type")))
    table.add_row("resolved_stages", ", ".join(summary.get("resolved_stages", [])))

    progress = summary.get("progress") or {}
    latest = progress.get("latest") or {}
    if latest:
        table.add_row("latest_stage", str(latest.get("stage")))
        table.add_row("latest_message", str(latest.get("message")))

    compare = summary.get("compare") or {}
    if compare:
        table.add_row("compare_status", str(compare.get("status")))
        diff = compare.get("diff") or {}
        for metric_name in ("roc_auc", "pr_auc"):
            metric_payload = diff.get(metric_name)
            if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
                table.add_row(f"{metric_name}_delta", f"{float(metric_payload['delta']):.4f}")

    console.print(table)
    return console.export_text(styles=False)


def render_progress_snapshot(progress: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, force_terminal=False, file=StringIO())
    console.print("Run Progress")
    table = Table(show_lines=True, box=box.SIMPLE)
    table.add_column("Field")
    table.add_column("Value")

    latest = (progress or {}).get("latest") or {}
    if latest:
        table.add_row("latest_stage", str(latest.get("stage")))
        table.add_row("latest_tool", str(latest.get("tool_name") or latest.get("event")))
        table.add_row("latest_message", str(latest.get("message")))

    stages = (progress or {}).get("stages") or {}
    for stage_name, state in stages.items():
        completed = state.get("completed")
        total = state.get("total")
        if completed is not None and total is not None:
            table.add_row(stage_name, f"{completed}/{total}")
        else:
            table.add_row(stage_name, "active")

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
    for metric_name in ("roc_auc", "pr_auc"):
        metric_payload = diff.get(metric_name)
        if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
            table.add_row(f"{metric_name}_delta", f"{float(metric_payload['delta']):.4f}")

    console.print(table)
    return console.export_text(styles=False)
