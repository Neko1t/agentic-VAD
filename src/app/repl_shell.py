from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.app import orchestrator
from src.app.models import WorkflowType
from src.app.repl_parser import CommandParseError, parse_command
from src.app.repl_renderer import (
    render_compare_summary,
    render_doctor_summary,
    render_progress_snapshot,
    render_repl_overview,
    render_result_summary,
    render_run_summary,
)
from src.app.run_monitor import WorkflowMonitor
from src.app.results import load_results
from src.app.status import build_repl_overview


def render_help_text() -> str:
    return "\n".join(
        [
            "Supported Commands",
            "- help",
            "- doctor",
            "- status",
            "- download models-core",
            "- download bootstrap",
            "- build mini",
            "- run mini",
            "- run full",
            "- run stage <name>",
            "- results",
            "- compare",
            "- clear",
            "- exit",
        ]
    )


def build_prompt_text(overview: dict[str, object]) -> str:
    mini_state = "ready" if overview.get("mini_ready") else "missing"
    full_state = "ready" if overview.get("full_ready") else "missing"
    return f"agentic-vad [mini:{mini_state} full:{full_state}] > "


def run_repl_session(
    *,
    repo_root: Path,
    preferred_dataset: str = "ucf_crime",
    emit_output: Callable[[str], None] = print,
) -> int:
    overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
    emit_output(render_repl_overview(overview))

    while True:
        try:
            raw = input(build_prompt_text(overview))
        except EOFError:
            return 0

        try:
            command = parse_command(raw)
        except CommandParseError as exc:
            emit_output(str(exc))
            continue

        if command.name == "help":
            emit_output(render_help_text())
            continue
        if command.name == "doctor":
            request = orchestrator.build_default_run_request(
                repo_root=repo_root,
                preferred_dataset=preferred_dataset,
                workflow_type=WorkflowType.MINI,
            )
            snapshot = orchestrator.doctor(
                root_path=request.root_path,
                annotation_file_path=request.annotation_file_path,
                captions_dir=request.captions_dir,
                temporal_annotation_file=request.temporal_annotation_file,
                baseline_scores_dir=request.baseline_scores_dir,
                output_dir=request.output_dir,
            )
            emit_output(render_doctor_summary(snapshot))
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "status":
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            emit_output(render_repl_overview(overview))
            continue
        if command.name == "results":
            summary = load_results(repo_root / "data" / "agentic_outputs")
            emit_output(render_result_summary(summary))
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "compare":
            summary = load_results(repo_root / "data" / "agentic_outputs")
            emit_output(render_compare_summary(summary))
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "download":
            preset = command.args[0] if command.args else "models-core"
            emit_output(
                f"Recommended external command:\npython {repo_root / 'scripts' / 'download_agentic_assets.py'} --preset {preset}"
            )
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "build" and command.args == ["mini"]:
            emit_output(
                f"Recommended external command:\npython {repo_root / 'scripts' / 'build_ucf_crime_mini_subset.py'}"
            )
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "run" and command.args == ["mini"]:
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            if not overview.get("mini_ready"):
                emit_output("mini dataset is not ready")
                continue
            request = orchestrator.build_default_run_request(
                repo_root=repo_root,
                preferred_dataset=preferred_dataset,
                workflow_type=WorkflowType.MINI,
            )
            monitor = WorkflowMonitor()
            summary = orchestrator.run(request, capture_progress=True, monitor=monitor)
            emit_output(render_progress_snapshot(monitor.snapshot()))
            emit_output(render_run_summary(summary))
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "run" and command.args == ["full"]:
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            if not overview.get("full_ready"):
                emit_output("full dataset is not ready")
                continue
            request = orchestrator.build_default_run_request(
                repo_root=repo_root,
                preferred_dataset=preferred_dataset,
                workflow_type=WorkflowType.FULL,
            )
            monitor = WorkflowMonitor()
            summary = orchestrator.run(request, capture_progress=True, monitor=monitor)
            emit_output(render_progress_snapshot(monitor.snapshot()))
            emit_output(render_run_summary(summary))
            overview = build_repl_overview(repo_root=repo_root, preferred_dataset=preferred_dataset)
            continue
        if command.name == "exit":
            return 0

        emit_output(f"command not implemented yet: {command.name}")
