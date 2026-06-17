from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from src.app import orchestrator
from src.app.models import RunRequest, WorkflowType
from src.app.repl_shell import run_repl_session
from src.app.tui_app import launch_home
from src.core.schemas import RunMode

app = typer.Typer(
    add_completion=False,
    help="Unified entrypoint for the agentic VAD project.",
)
assets_app = typer.Typer(add_completion=False, help="Asset download helpers.")
dataset_app = typer.Typer(add_completion=False, help="Dataset preparation helpers.")
run_app = typer.Typer(add_completion=False, help="Experiment runners.")
results_app = typer.Typer(add_completion=False, help="Inspect persisted results.")

app.add_typer(assets_app, name="assets")
app.add_typer(dataset_app, name="dataset")
app.add_typer(run_app, name="run")
app.add_typer(results_app, name="results")


def _dump_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    repo_root = Path(__file__).resolve().parents[2]
    run_repl_session(repo_root=repo_root, preferred_dataset="ucf_crime", emit_output=typer.echo)
    raise typer.Exit()


@app.command()
def doctor(
    root_path: Path = typer.Option(..., help="Frames root directory."),
    annotation_file_path: Path = typer.Option(..., help="Split annotation file."),
    captions_dir: Path = typer.Option(..., help="Caption JSON directory."),
    temporal_annotation_file: Optional[Path] = typer.Option(None, help="Temporal annotation file."),
    baseline_scores_dir: Optional[Path] = typer.Option(None, help="Baseline refined scores directory."),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs"), help="Output directory."),
) -> None:
    snapshot = orchestrator.doctor(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        output_dir=output_dir,
    )
    _dump_json(snapshot.model_dump(mode="json"))


def _build_run_request(
    workflow_type: WorkflowType,
    *,
    root_path: Path,
    annotation_file_path: Path,
    captions_dir: Path,
    output_dir: Path,
    memory_dir: Path,
    temporal_annotation_file: Optional[Path],
    baseline_scores_dir: Optional[Path],
    baseline_metrics_dir: Optional[Path],
    stage_names: list[str],
    frame_interval: int,
    rolling_window_size: int,
    use_audio: bool,
    use_ocr: bool,
    top_k: int,
    run_mode: RunMode,
    use_chroma: bool,
    export_eval_scores: bool,
    normal_label: int,
    video_fps: float,
    gpu_device: str,
    use_vlm: bool,
    video_root_path: Optional[Path],
    vlm_model_path: Optional[Path],
) -> RunRequest:
    return RunRequest(
        workflow_type=workflow_type,
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
        stage_names=stage_names,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        normal_label=normal_label,
        video_fps=video_fps,
        gpu_device=gpu_device,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )


@run_app.command("mini")
def run_mini(
    root_path: Path = typer.Option(...),
    annotation_file_path: Path = typer.Option(...),
    captions_dir: Path = typer.Option(...),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    temporal_annotation_file: Optional[Path] = typer.Option(None),
    baseline_scores_dir: Optional[Path] = typer.Option(None),
    baseline_metrics_dir: Optional[Path] = typer.Option(None),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
    run_mode: RunMode = typer.Option(RunMode.ONLINE_INFERENCE),
    use_chroma: bool = typer.Option(True),
    export_eval_scores: bool = typer.Option(True),
    normal_label: int = typer.Option(0),
    video_fps: float = typer.Option(30.0),
    gpu_device: str = typer.Option(..., help="Physical GPU index to reserve, for example 0 or 1."),
    use_vlm: bool = typer.Option(False, "--use-vlm/--no-use-vlm"),
    video_root_path: Optional[Path] = typer.Option(None),
    vlm_model_path: Optional[Path] = typer.Option(None),
) -> None:
    request = _build_run_request(
        WorkflowType.MINI,
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
        stage_names=[],
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        normal_label=normal_label,
        video_fps=video_fps,
        gpu_device=gpu_device,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )
    _dump_json(orchestrator.run(request))


@run_app.command("full")
def run_full(
    root_path: Path = typer.Option(...),
    annotation_file_path: Path = typer.Option(...),
    captions_dir: Path = typer.Option(...),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    temporal_annotation_file: Optional[Path] = typer.Option(None),
    baseline_scores_dir: Optional[Path] = typer.Option(None),
    baseline_metrics_dir: Optional[Path] = typer.Option(None),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
    run_mode: RunMode = typer.Option(RunMode.ONLINE_INFERENCE),
    use_chroma: bool = typer.Option(True),
    export_eval_scores: bool = typer.Option(True),
    normal_label: int = typer.Option(0),
    video_fps: float = typer.Option(30.0),
    gpu_device: str = typer.Option(..., help="Physical GPU index to reserve, for example 0 or 1."),
    use_vlm: bool = typer.Option(False, "--use-vlm/--no-use-vlm"),
    video_root_path: Optional[Path] = typer.Option(None),
    vlm_model_path: Optional[Path] = typer.Option(None),
) -> None:
    request = _build_run_request(
        WorkflowType.FULL,
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
        stage_names=[],
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        normal_label=normal_label,
        video_fps=video_fps,
        gpu_device=gpu_device,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )
    _dump_json(orchestrator.run(request))


@run_app.command("stage")
def run_stage(
    stage: list[str] = typer.Argument(..., help="Stage names such as pipeline metrics compare."),
    root_path: Path = typer.Option(...),
    annotation_file_path: Path = typer.Option(...),
    captions_dir: Path = typer.Option(...),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    temporal_annotation_file: Optional[Path] = typer.Option(None),
    baseline_scores_dir: Optional[Path] = typer.Option(None),
    baseline_metrics_dir: Optional[Path] = typer.Option(None),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
    run_mode: RunMode = typer.Option(RunMode.ONLINE_INFERENCE),
    use_chroma: bool = typer.Option(True),
    export_eval_scores: bool = typer.Option(True),
    normal_label: int = typer.Option(0),
    video_fps: float = typer.Option(30.0),
    gpu_device: str = typer.Option(..., help="Physical GPU index to reserve, for example 0 or 1."),
    use_vlm: bool = typer.Option(False, "--use-vlm/--no-use-vlm"),
    video_root_path: Optional[Path] = typer.Option(None),
    vlm_model_path: Optional[Path] = typer.Option(None),
) -> None:
    request = _build_run_request(
        WorkflowType.STAGE,
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
        stage_names=stage,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        normal_label=normal_label,
        video_fps=video_fps,
        gpu_device=gpu_device,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )
    _dump_json(orchestrator.run(request))


@assets_app.command("download")
def assets_download(args: list[str] = typer.Argument(None)) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raise SystemExit(orchestrator.launch_asset_downloader(repo_root, args or []))


@dataset_app.command("build-mini")
def dataset_build_mini(args: list[str] = typer.Argument(None)) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raise SystemExit(orchestrator.launch_mini_subset_builder(repo_root, args or []))


@results_app.command("show")
def results_show(
    run_root: Path = typer.Option(Path("./data/agentic_outputs")),
) -> None:
    summary = orchestrator.show_results(run_root)
    _dump_json(summary.model_dump(mode="json"))
