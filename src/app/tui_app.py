from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.app import orchestrator
from src.app.models import RunRequest, WorkflowType
from src.app.dashboard import build_compare_summary_rows, build_recent_result_rows, render_dashboard
from src.app.run_monitor import WorkflowMonitor
from src.app.status import build_status_snapshot, build_workspace_snapshot
from src.core.schemas import RunMode

TEXTUAL_AVAILABLE = False
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, VerticalScroll
    from textual.widgets import Button, Footer, Header, Static

    TEXTUAL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    App = object  # type: ignore[assignment]
    ComposeResult = object  # type: ignore[assignment]
    Container = object  # type: ignore[assignment]
    Horizontal = object  # type: ignore[assignment]
    VerticalScroll = object  # type: ignore[assignment]
    Button = object  # type: ignore[assignment]
    Header = object  # type: ignore[assignment]
    Footer = object  # type: ignore[assignment]
    Static = object  # type: ignore[assignment]


def build_home_sections(*, snapshot, workspace: dict[str, Any]) -> dict[str, str]:
    run_state = "running" if workspace.get("is_running") else "idle"
    project_status = "\n".join(f"- {check.name}: [{check.level}] {check.message}" for check in snapshot.checks) or "- no checks"
    dataset_readiness = "\n".join(
        f"- {item['name']}: {'ready' if item['ready'] else 'missing'} ({item['path']})"
        for item in workspace.get("datasets", [])
    ) or "- no dataset info"
    model_assets = "\n".join(
        f"- {item.get('name', 'model')}: {'ready' if item['ready'] else 'missing'} ({item['path']})"
        for item in workspace.get("models", [])
    ) or "- no model info"
    recent_results = "\n".join(
        f"- {key}: {value}" for key, value in build_recent_result_rows(workspace.get("recent_result"))
    ) or "- no recent results"
    compare_summary = "\n".join(
        f"- {key}: {value}" for key, value in build_compare_summary_rows(workspace.get("recent_result"))
    ) or "- no comparison summary"
    live_progress_payload = workspace.get("live_progress") or {}
    latest_progress = live_progress_payload.get("latest") or {}
    stage_progress = live_progress_payload.get("stages") or {}
    live_progress_lines: list[str] = []
    if latest_progress:
        live_progress_lines.append(
            f"- latest: {latest_progress.get('stage')} | {latest_progress.get('tool_name') or latest_progress.get('event')} | {latest_progress.get('message')}"
        )
    for stage_name, stage_state in stage_progress.items():
        completed = stage_state.get("completed")
        total = stage_state.get("total")
        if completed is not None and total is not None:
            live_progress_lines.append(f"- {stage_name}: {completed}/{total}")
        else:
            live_progress_lines.append(f"- {stage_name}: active")
    live_progress = "\n".join(live_progress_lines) or "- no live progress captured"
    run_state_summary = f"- state: {run_state}"
    required_actions = "\n".join(f"- {item}" for item in workspace.get("required_actions", [])) or "- all core checks look good"
    suggested_commands = "\n".join(
        [
            "- doctor: python agentic_vad.py doctor --help",
            "- assets: python agentic_vad.py assets download --preset models-core",
            "- mini subset: python agentic_vad.py dataset build-mini",
            "- mini run: python agentic_vad.py run mini --help",
            "- full run: python agentic_vad.py run full --help",
            "- results: python agentic_vad.py results show --help",
        ]
    )
    return {
        "overview": "Unified project entry for experiments, diagnostics, and result inspection.",
        "run_state": run_state_summary,
        "project_status": project_status,
        "dataset_readiness": dataset_readiness,
        "model_assets": model_assets,
        "recent_results": recent_results,
        "compare_summary": compare_summary,
        "live_progress": live_progress,
        "required_actions": required_actions,
        "suggested_commands": suggested_commands,
    }


def build_default_run_request(*, repo_root: Path, preferred_dataset: str, workflow_kind: str = "mini") -> RunRequest:
    dataset_name = f"{preferred_dataset}_mini" if workflow_kind == "mini" else preferred_dataset
    workflow_type = WorkflowType.MINI if workflow_kind == "mini" else WorkflowType.FULL
    return RunRequest(
        workflow_type=workflow_type,
        root_path=repo_root / "data" / dataset_name / "frames",
        annotation_file_path=repo_root / "data" / dataset_name / "annotations" / "test.txt",
        captions_dir=repo_root / "data" / dataset_name / "captions" / "video_llama3_json_results",
        output_dir=repo_root / "data" / "agentic_outputs" / dataset_name,
        memory_dir=repo_root / "data" / "agentic_memory" / dataset_name,
        temporal_annotation_file=repo_root
        / "data"
        / dataset_name
        / "annotations"
        / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
        baseline_scores_dir=repo_root / "data" / dataset_name / "refined_scores" / "videollama3",
        run_mode=RunMode.ONLINE_INFERENCE,
    )


class AgenticVADApp(App):  # type: ignore[misc]
    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    .column {
        width: 1fr;
        height: 100%;
        padding: 0 1;
    }
    .panel {
        border: round $surface;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, repo_root: Path, preferred_dataset: str = "ucf_crime"):
        super().__init__()
        self.repo_root = repo_root
        self.preferred_dataset = preferred_dataset
        self.home_state = collect_home_state(repo_root=repo_root, preferred_dataset=preferred_dataset)
        self.thread_factory = lambda target, name, daemon: threading.Thread(target=target, name=name, daemon=daemon)
        self.is_running = False
        self.active_monitor: WorkflowMonitor | None = None
        self.run_workflow_callable = self.run_default_workflow
        self.home_state["workspace"]["is_running"] = self.is_running
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=self.home_state["workspace"],
        )

    BINDINGS = [("r", "refresh", "Refresh")]

    def refresh_home_state(self) -> None:
        self.home_state = collect_home_state(repo_root=self.repo_root, preferred_dataset=self.preferred_dataset)
        self.home_state["workspace"]["is_running"] = self.is_running
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=self.home_state["workspace"],
        )

    def refresh_live_sections(self) -> None:
        self.poll_live_progress()
        if not TEXTUAL_AVAILABLE:
            return
        try:
            self.query_one("#run_state", Static).update(f"Run State\n{self.sections['run_state']}")
            self.query_one("#live_progress", Static).update(f"Live Progress\n{self.sections['live_progress']}")
            self.query_one("#recent_results", Static).update(f"Recent Results\n{self.sections['recent_results']}")
            self.query_one("#compare_summary", Static).update(f"Compare Summary\n{self.sections['compare_summary']}")
            self.query_one("#required_actions", Static).update(
                f"Required Actions\n{self.sections['required_actions']}"
            )
        except Exception:
            return

    def poll_live_progress(self) -> None:
        if self.active_monitor is None:
            return
        self.home_state["workspace"]["live_progress"] = self.active_monitor.snapshot()
        self.home_state["workspace"]["is_running"] = self.is_running
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=self.home_state["workspace"],
        )

    def on_mount(self) -> None:
        if TEXTUAL_AVAILABLE:
            self.set_interval(0.5, self.refresh_live_sections)

    def apply_run_summary(self, summary: dict[str, Any]) -> None:
        workspace = self.home_state["workspace"]
        workspace["live_progress"] = summary.get("progress")
        workspace["is_running"] = self.is_running
        compare = summary.get("compare") or {}
        workflow_summary_path = summary.get("workflow_summary_path")
        workspace["recent_result"] = {
            "status": compare.get("status") or "completed",
            "summary": f"workflow finished for {summary.get('workflow_type', 'run')}",
            "path": workflow_summary_path or "",
            "comparison": compare if isinstance(compare, dict) else {},
        }
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=workspace,
        )

    def mark_run_started(self, workflow_kind: str) -> None:
        self.is_running = True
        workspace = self.home_state["workspace"]
        workspace["is_running"] = self.is_running
        workspace["live_progress"] = {
            "latest": {
                "stage": "workflow",
                "event": "run_start",
                "message": f"running {workflow_kind} workflow",
                "tool_name": None,
            },
            "stages": {},
        }
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=workspace,
        )

    def complete_background_run(self, summary: dict[str, Any]) -> None:
        self.is_running = False
        self.active_monitor = None
        self.home_state["workspace"]["is_running"] = self.is_running
        self.apply_run_summary(summary)

    def fail_background_run(self, exc: Exception) -> None:
        self.is_running = False
        self.active_monitor = None
        workspace = self.home_state["workspace"]
        workspace["is_running"] = self.is_running
        workspace["live_progress"] = {
            "latest": {
                "stage": "workflow",
                "event": "run_failed",
                "message": str(exc),
                "tool_name": None,
            },
            "stages": {},
        }
        self.sections = build_home_sections(
            snapshot=self.home_state["snapshot"],
            workspace=workspace,
        )

    def run_default_workflow(self, workflow_kind: str = "mini") -> dict[str, Any]:
        request = build_default_run_request(
            repo_root=self.repo_root,
            preferred_dataset=self.preferred_dataset,
            workflow_kind=workflow_kind,
        )
        if self.active_monitor is None:
            self.active_monitor = WorkflowMonitor()
        summary = orchestrator.run(request, capture_progress=True, monitor=self.active_monitor)
        self.apply_run_summary(summary)
        return summary

    def start_background_run(self, workflow_kind: str) -> None:
        self.mark_run_started(workflow_kind)
        self.active_monitor = WorkflowMonitor()

        def _runner() -> None:
            try:
                summary = self.run_workflow_callable(workflow_kind)
            except Exception as exc:  # pragma: no cover - exercised via test
                self.fail_background_run(exc)
                return
            if isinstance(summary, dict):
                self.complete_background_run(summary)

        thread = self.thread_factory(_runner, f"agentic-vad-{workflow_kind}", True)
        thread.start()
        return None

    def action_run_mini(self) -> None:
        self.start_background_run("mini")

    def action_run_full(self) -> None:
        self.start_background_run("full")

    def action_show_help(self) -> None:
        self.mark_run_started("help")

    def compose(self) -> "ComposeResult":
        yield Header(show_clock=True)
        with Container(id="main"):
            yield Static(self.sections["overview"], classes="panel", id="overview")
            with Horizontal():
                with VerticalScroll(classes="column"):
                    with Container(classes="panel", id="run_controls"):
                        yield Static("Run Controls")
                        yield Button("Run Mini", id="run_mini")
                        yield Button("Run Full", id="run_full")
                    yield Static(f"Run State\n{self.sections['run_state']}", classes="panel", id="run_state")
                    yield Static(f"Project Status\n{self.sections['project_status']}", classes="panel", id="project_status")
                    yield Static(
                        f"Dataset Readiness\n{self.sections['dataset_readiness']}",
                        classes="panel",
                        id="dataset_readiness",
                    )
                    yield Static(f"Model Assets\n{self.sections['model_assets']}", classes="panel", id="model_assets")
                with VerticalScroll(classes="column"):
                    yield Static(f"Recent Results\n{self.sections['recent_results']}", classes="panel", id="recent_results")
                    yield Static(f"Compare Summary\n{self.sections['compare_summary']}", classes="panel", id="compare_summary")
                    yield Static(f"Live Progress\n{self.sections['live_progress']}", classes="panel", id="live_progress")
                    yield Static(
                        f"Required Actions\n{self.sections['required_actions']}",
                        classes="panel",
                        id="required_actions",
                    )
                    yield Static(
                        f"Suggested Commands\n{self.sections['suggested_commands']}",
                        classes="panel",
                        id="suggested_commands",
                    )
        yield Footer()

    def action_refresh(self) -> None:
        self.refresh_home_state()
        if not TEXTUAL_AVAILABLE:
            return
        self.query_one("#overview", Static).update(self.sections["overview"])
        self.query_one("#run_state", Static).update(f"Run State\n{self.sections['run_state']}")
        self.query_one("#project_status", Static).update(f"Project Status\n{self.sections['project_status']}")
        self.query_one("#dataset_readiness", Static).update(
            f"Dataset Readiness\n{self.sections['dataset_readiness']}"
        )
        self.query_one("#model_assets", Static).update(f"Model Assets\n{self.sections['model_assets']}")
        self.query_one("#recent_results", Static).update(f"Recent Results\n{self.sections['recent_results']}")
        self.query_one("#compare_summary", Static).update(f"Compare Summary\n{self.sections['compare_summary']}")
        self.query_one("#live_progress", Static).update(f"Live Progress\n{self.sections['live_progress']}")
        self.query_one("#required_actions", Static).update(
            f"Required Actions\n{self.sections['required_actions']}"
        )
        self.query_one("#suggested_commands", Static).update(
            f"Suggested Commands\n{self.sections['suggested_commands']}"
        )

    def on_button_pressed(self, event) -> None:  # pragma: no cover - covered via unit action methods
        if getattr(event.button, "id", None) == "run_mini":
            self.action_run_mini()
        elif getattr(event.button, "id", None) == "run_full":
            self.action_run_full()


def create_textual_app(repo_root: Path, preferred_dataset: str = "ucf_crime") -> AgenticVADApp:
    return AgenticVADApp(repo_root=repo_root, preferred_dataset=preferred_dataset)


def collect_home_state(*, repo_root: Path, preferred_dataset: str = "ucf_crime") -> dict[str, Any]:
    snapshot = build_status_snapshot(
        root_path=repo_root / "data" / preferred_dataset / "frames",
        annotation_file_path=repo_root / "data" / preferred_dataset / "annotations" / "test.txt",
        captions_dir=repo_root / "data" / preferred_dataset / "captions" / "video_llama3_json_results",
        temporal_annotation_file=repo_root
        / "data"
        / preferred_dataset
        / "annotations"
        / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
        baseline_scores_dir=repo_root / "data" / preferred_dataset / "refined_scores" / "videollama3",
        output_dir=repo_root / "data" / "agentic_outputs",
    )
    workspace = build_workspace_snapshot(repo_root=repo_root, preferred_dataset=preferred_dataset)
    return {"snapshot": snapshot, "workspace": workspace}


def launch_home(
    *,
    repo_root: Path,
    preferred_dataset: str = "ucf_crime",
    force_textual: bool = False,
    force_text: bool = False,
) -> str | None:
    if force_text:
        force_textual = False
    elif TEXTUAL_AVAILABLE:
        force_textual = True
    if TEXTUAL_AVAILABLE and force_textual:
        app = create_textual_app(repo_root=repo_root, preferred_dataset=preferred_dataset)
        app.run()
        return None

    state = collect_home_state(repo_root=repo_root, preferred_dataset=preferred_dataset)
    return render_dashboard(snapshot=state["snapshot"], workspace=state["workspace"])
