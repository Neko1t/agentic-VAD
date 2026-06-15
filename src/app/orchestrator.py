from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.app.models import ProjectStatusSnapshot, ResultSummary, RunRequest, WorkflowType
from src.app.run_monitor import QueueProgressReporter, WorkflowMonitor
from src.app.results import load_results
from src.app.status import build_status_snapshot
from src.app.workflows import resolve_workflow_stages
from src.core.schemas import RunMode
from src.pipelines.run_agentic_workflow import run_workflow
from src.runtime.progress import NullProgressReporter


def doctor(
    *,
    root_path: Path,
    annotation_file_path: Path,
    captions_dir: Path,
    temporal_annotation_file: Path | None = None,
    baseline_scores_dir: Path | None = None,
    output_dir: Path | None = None,
) -> ProjectStatusSnapshot:
    return build_status_snapshot(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        output_dir=output_dir,
    )


def build_default_run_request(
    *,
    repo_root: Path,
    preferred_dataset: str = "ucf_crime",
    workflow_type: WorkflowType = WorkflowType.MINI,
) -> RunRequest:
    dataset_name = f"{preferred_dataset}_mini" if workflow_type == WorkflowType.MINI else preferred_dataset
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


def run(
    request: RunRequest,
    *,
    capture_progress: bool = False,
    monitor: WorkflowMonitor | None = None,
) -> dict[str, Any]:
    selected_stages = resolve_workflow_stages(request)
    progress_reporter = NullProgressReporter()
    active_monitor = monitor
    if capture_progress:
        if active_monitor is None:
            active_monitor = WorkflowMonitor()
        progress_reporter = QueueProgressReporter(active_monitor)
    summary = run_workflow(
        root_path=request.root_path,
        annotation_file_path=request.annotation_file_path,
        captions_dir=request.captions_dir,
        output_dir=request.output_dir,
        memory_dir=request.memory_dir,
        temporal_annotation_file=request.temporal_annotation_file,
        baseline_scores_dir=request.baseline_scores_dir,
        baseline_metrics_dir=request.baseline_metrics_dir,
        stages=selected_stages,
        frame_interval=request.frame_interval,
        rolling_window_size=request.rolling_window_size,
        use_audio=request.use_audio,
        use_ocr=request.use_ocr,
        top_k=request.top_k,
        run_mode=request.run_mode,
        use_chroma=request.use_chroma,
        export_eval_scores=request.export_eval_scores,
        normal_label=request.normal_label,
        video_fps=request.video_fps,
        progress_reporter=progress_reporter,
    )
    summary["workflow_type"] = request.workflow_type.value
    summary["resolved_stages"] = [stage.value for stage in selected_stages]
    summary["request"] = json.loads(request.model_dump_json())
    if active_monitor is not None:
        summary["progress"] = active_monitor.snapshot()
    return summary


def show_results(run_root: Path) -> ResultSummary:
    return load_results(run_root)


def launch_asset_downloader(repo_root: Path, extra_args: list[str]) -> int:
    command = [sys.executable, str(repo_root / "scripts" / "download_agentic_assets.py"), *extra_args]
    return subprocess.run(command, check=False).returncode


def launch_mini_subset_builder(repo_root: Path, extra_args: list[str]) -> int:
    command = [sys.executable, str(repo_root / "scripts" / "build_ucf_crime_mini_subset.py"), *extra_args]
    return subprocess.run(command, check=False).returncode
