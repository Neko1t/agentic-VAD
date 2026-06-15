from __future__ import annotations

from io import StringIO
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.app.models import ProjectStatusSnapshot


def build_recent_result_rows(recent_result: dict[str, Any] | None) -> list[tuple[str, str]]:
    if recent_result is None:
        return [("status", "no persisted comparison report found")]

    rows = [
        ("status", str(recent_result.get("status"))),
        ("summary", str(recent_result.get("summary"))),
        ("path", str(recent_result.get("path"))),
    ]
    comparison = recent_result.get("comparison") or {}
    diff = comparison.get("diff") or {}
    for metric_name in ("roc_auc", "pr_auc"):
        metric_payload = diff.get(metric_name)
        if isinstance(metric_payload, dict) and metric_payload.get("delta") is not None:
            rows.append((f"{metric_name}_delta", f"{float(metric_payload['delta']):.4f}"))
    return rows


def render_dashboard(*, snapshot: ProjectStatusSnapshot, workspace: dict[str, Any]) -> str:
    console = Console(record=True, width=120, legacy_windows=False, file=StringIO())

    console.print(Panel("Unified project entry for experiments, diagnostics, and result inspection.", title="Agentic VAD"))

    status_table = Table(title="Project Status", show_lines=True)
    status_table.add_column("Check")
    status_table.add_column("Level")
    status_table.add_column("Message")
    for check in snapshot.checks:
        status_table.add_row(check.name, check.level, check.message)
    console.print(status_table)

    dataset_table = Table(title="Dataset Readiness", show_lines=True)
    dataset_table.add_column("Dataset")
    dataset_table.add_column("Ready")
    dataset_table.add_column("Path")
    for item in workspace.get("datasets", []):
        dataset_table.add_row(item["name"], "yes" if item["ready"] else "no", item["path"])
    console.print(dataset_table)

    model_table = Table(title="Model Assets", show_lines=True)
    model_table.add_column("Name")
    model_table.add_column("Path")
    model_table.add_column("Ready")
    for item in workspace.get("models", []):
        model_table.add_row(item.get("name", "model"), item["path"], "yes" if item["ready"] else "no")
    console.print(model_table)

    recent_result = workspace.get("recent_result")
    result_table = Table(title="Recent Results", show_lines=True)
    result_table.add_column("Field")
    result_table.add_column("Value")
    for key, value in build_recent_result_rows(recent_result):
        result_table.add_row(key, value)
    console.print(result_table)

    actions = workspace.get("required_actions", [])
    if not actions:
        actions = ["all core checks look good"]
    action_table = Table(title="Required Actions", show_lines=True)
    action_table.add_column("Action")
    for action in actions:
        action_table.add_row(str(action))
    console.print(action_table)

    command_table = Table(title="Suggested Commands", show_lines=True)
    command_table.add_column("Purpose")
    command_table.add_column("Command")
    command_table.add_row("Inspect environment", "python agentic_vad.py doctor --help")
    command_table.add_row("Download assets", "python agentic_vad.py assets download --preset models-core")
    command_table.add_row("Build mini subset", "python agentic_vad.py dataset build-mini")
    command_table.add_row("Run mini experiment", "python agentic_vad.py run mini --help")
    command_table.add_row("Run full experiment", "python agentic_vad.py run full --help")
    command_table.add_row("Inspect results", "python agentic_vad.py results show --help")
    console.print(command_table)

    return console.export_text(styles=False)
