from __future__ import annotations

import json
import math
from contextlib import nullcontext
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Optional

import typer

from src.core.schemas import RunMode
from src.eval.agentic_vad_metrics import load_metric_report, run_metrics
from src.pipelines.extract_patterns_offline import extract_patterns
from src.pipelines.promote_case_memory import promote_cases
from src.pipelines.run_agentic_vad import run_pipeline
from src.runtime.progress import PrefixedProgressReporter, ProgressEvent, RichProgressReporter

app = typer.Typer(add_completion=False, help="Run the end-to-end agentic VAD workflow with progress and metric comparison.")


class WorkflowStage(str, Enum):
    PIPELINE = "pipeline"
    PROMOTE = "promote"
    PATTERNS = "patterns"
    METRICS = "metrics"
    BASELINE_METRICS = "baseline-metrics"
    COMPARE = "compare"


def _default_stages(include_baseline_metrics: bool) -> list[WorkflowStage]:
    stages = [
        WorkflowStage.PIPELINE,
        WorkflowStage.PROMOTE,
        WorkflowStage.PATTERNS,
        WorkflowStage.METRICS,
    ]
    if include_baseline_metrics:
        stages.append(WorkflowStage.BASELINE_METRICS)
    stages.append(WorkflowStage.COMPARE)
    return stages


def resolve_stages(
    requested_stages: Iterable[WorkflowStage] | None,
    *,
    baseline_scores_dir: Path | None,
    baseline_metrics_dir: Path | None,
) -> list[WorkflowStage]:
    if requested_stages:
        requested = list(dict.fromkeys(requested_stages))
    else:
        requested = _default_stages(include_baseline_metrics=baseline_scores_dir is not None or baseline_metrics_dir is not None)

    if WorkflowStage.COMPARE in requested and WorkflowStage.METRICS not in requested:
        requested.insert(0, WorkflowStage.METRICS)
    if (
        WorkflowStage.COMPARE in requested
        and baseline_scores_dir is not None
        and WorkflowStage.BASELINE_METRICS not in requested
    ):
        insert_at = requested.index(WorkflowStage.COMPARE)
        requested.insert(insert_at, WorkflowStage.BASELINE_METRICS)
    if WorkflowStage.BASELINE_METRICS in requested and baseline_scores_dir is None and baseline_metrics_dir is None:
        requested = [stage for stage in requested if stage != WorkflowStage.BASELINE_METRICS]

    order = [
        WorkflowStage.PIPELINE,
        WorkflowStage.PROMOTE,
        WorkflowStage.PATTERNS,
        WorkflowStage.METRICS,
        WorkflowStage.BASELINE_METRICS,
        WorkflowStage.COMPARE,
    ]
    return [stage for stage in order if stage in requested]


def compare_metric_reports(
    agentic_report: dict[str, Any],
    baseline_report: dict[str, Any] | None,
) -> dict[str, Any]:
    comparison: dict[str, Any] = {"agentic": agentic_report, "baseline": baseline_report}
    diffs: dict[str, Any] = {}
    for metric_name in ("roc_auc", "pr_auc"):
        agentic_value = agentic_report.get(metric_name)
        baseline_value = baseline_report.get(metric_name) if baseline_report else None
        if (
            isinstance(agentic_value, (int, float))
            and isinstance(baseline_value, (int, float))
            and math.isfinite(float(agentic_value))
            and math.isfinite(float(baseline_value))
        ):
            diffs[metric_name] = {
                "agentic": round(float(agentic_value), 6),
                "baseline": round(float(baseline_value), 6),
                "delta": round(float(agentic_value) - float(baseline_value), 6),
            }
        else:
            diffs[metric_name] = {
                "agentic": agentic_value,
                "baseline": baseline_value,
                "delta": None,
            }
    comparison["diff"] = diffs
    if baseline_report is None:
        comparison["status"] = "baseline_unavailable"
        comparison["message"] = "Provide baseline_scores_dir or baseline_metrics_dir for an apples-to-apples comparison."
    else:
        comparison["status"] = "ok"
    return comparison


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def run_workflow(
    *,
    root_path: Path,
    annotation_file_path: Path,
    captions_dir: Path,
    output_dir: Path = Path("./data/agentic_outputs"),
    memory_dir: Path = Path("./data/agentic_memory"),
    temporal_annotation_file: Optional[Path] = None,
    baseline_scores_dir: Optional[Path] = None,
    baseline_metrics_dir: Optional[Path] = None,
    stages: Optional[List[WorkflowStage]] = None,
    frame_interval: int = 16,
    rolling_window_size: int = 4,
    use_audio: bool = False,
    use_ocr: bool = False,
    top_k: int = 5,
    run_mode: RunMode = RunMode.ONLINE_INFERENCE,
    use_chroma: bool = True,
    export_eval_scores: bool = True,
    promote_dry_run: bool = False,
    promote_high_risk_threshold: float = 8.0,
    promote_hard_negative_threshold: float = 2.5,
    promote_max_uncertainty: float = 0.35,
    promote_min_evidence_tags: int = 1,
    pattern_min_support: int = 2,
    normal_label: int = 0,
    video_fps: float = 30.0,
    progress_reporter=None,
) -> dict[str, Any]:
    selected_stages = resolve_stages(
        stages,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
    )
    reporter = progress_reporter
    if reporter is None:
        reporter = RichProgressReporter()

    summary: dict[str, Any] = {
        "selected_stages": [stage.value for stage in selected_stages],
        "output_dir": str(output_dir),
        "memory_dir": str(memory_dir),
    }

    manager = reporter if hasattr(reporter, "__enter__") else nullcontext(reporter)
    with manager:
        total_stages = len(selected_stages)
        for stage_index, stage in enumerate(selected_stages, start=1):
            prefixed = PrefixedProgressReporter(reporter, prefix=f"[{stage_index}/{total_stages}] {stage.value}")
            prefixed.emit(ProgressEvent(stage="workflow", event="stage_start", message="starting"))

            if stage == WorkflowStage.PIPELINE:
                pipeline_summary = run_pipeline(
                    root_path=root_path,
                    annotation_file_path=annotation_file_path,
                    captions_dir=captions_dir,
                    output_dir=output_dir,
                    memory_dir=memory_dir,
                    frame_interval=frame_interval,
                    rolling_window_size=rolling_window_size,
                    use_audio=use_audio,
                    use_ocr=use_ocr,
                    top_k=top_k,
                    run_mode=run_mode,
                    use_chroma=use_chroma,
                    export_eval_scores=export_eval_scores,
                    progress_reporter=prefixed,
                )
                summary["pipeline"] = pipeline_summary
            elif stage == WorkflowStage.PROMOTE:
                report_path = output_dir / "promotion_report.json"
                promotion = promote_cases(
                    memory_dir=memory_dir,
                    dry_run=promote_dry_run,
                    high_risk_threshold=promote_high_risk_threshold,
                    hard_negative_threshold=promote_hard_negative_threshold,
                    max_uncertainty=promote_max_uncertainty,
                    min_evidence_tags=promote_min_evidence_tags,
                )
                _write_json(report_path, promotion)
                summary["promote"] = {**promotion, "report_path": str(report_path)}
                prefixed.emit(ProgressEvent(stage="promote", event="stage_end", message=f"promoted {promotion['counts']['promoted']}"))
            elif stage == WorkflowStage.PATTERNS:
                patterns = extract_patterns(memory_dir=memory_dir, min_support=pattern_min_support)
                summary["patterns"] = patterns
                prefixed.emit(ProgressEvent(stage="patterns", event="stage_end", message=f"patterns {patterns['pattern_count']}"))
            elif stage == WorkflowStage.METRICS:
                if temporal_annotation_file is None:
                    raise ValueError("temporal_annotation_file is required for metrics and compare stages")
                metrics_output_dir = output_dir / "metrics"
                metrics = run_metrics(
                    root_path=root_path,
                    annotation_file_path=annotation_file_path,
                    temporal_annotation_file=temporal_annotation_file,
                    scores_dir=output_dir / "scores",
                    captions_dir=captions_dir,
                    output_dir=metrics_output_dir,
                    frame_interval=frame_interval,
                    normal_label=normal_label,
                    video_fps=video_fps,
                    quiet=True,
                )
                summary["metrics"] = metrics
                prefixed.emit(ProgressEvent(stage="metrics", event="stage_end", message=f"roc={metrics.get('roc_auc', 'n/a')}"))
            elif stage == WorkflowStage.BASELINE_METRICS:
                if temporal_annotation_file is None:
                    raise ValueError("temporal_annotation_file is required for baseline metrics")
                if baseline_scores_dir is not None:
                    baseline_output_dir = output_dir / "baseline_metrics"
                    baseline_metrics = run_metrics(
                        root_path=root_path,
                        annotation_file_path=annotation_file_path,
                        temporal_annotation_file=temporal_annotation_file,
                        scores_dir=baseline_scores_dir,
                        captions_dir=captions_dir,
                        output_dir=baseline_output_dir,
                        frame_interval=frame_interval,
                        normal_label=normal_label,
                        video_fps=video_fps,
                        quiet=True,
                    )
                elif baseline_metrics_dir is not None:
                    baseline_metrics = load_metric_report(baseline_metrics_dir)
                else:
                    baseline_metrics = None
                summary["baseline_metrics"] = baseline_metrics
                prefixed.emit(ProgressEvent(stage="baseline_metrics", event="stage_end", message="baseline ready"))
            elif stage == WorkflowStage.COMPARE:
                comparison = compare_metric_reports(
                    agentic_report=summary.get("metrics", {}),
                    baseline_report=summary.get("baseline_metrics"),
                )
                comparison_path = output_dir / "comparison_report.json"
                _write_json(comparison_path, comparison)
                summary["compare"] = {**comparison, "comparison_path": str(comparison_path)}
                prefixed.emit(ProgressEvent(stage="compare", event="stage_end", message=f"status={comparison['status']}"))

        workflow_summary_path = output_dir / "workflow_summary.json"
        summary["workflow_summary_path"] = str(workflow_summary_path)
        _write_json(workflow_summary_path, summary)
        reporter.emit(ProgressEvent(stage="workflow", event="run_complete", message="all stages completed"))
    return _json_safe(summary)


@app.command()
def main(
    root_path: Path = typer.Option(..., exists=True, file_okay=False),
    annotation_file_path: Path = typer.Option(..., exists=True, dir_okay=False),
    captions_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    temporal_annotation_file: Optional[Path] = typer.Option(None, exists=True, dir_okay=False),
    baseline_scores_dir: Optional[Path] = typer.Option(None, exists=True, file_okay=False),
    baseline_metrics_dir: Optional[Path] = typer.Option(None, exists=True, file_okay=False),
    stage: Optional[List[WorkflowStage]] = typer.Option(None, "--stage"),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
    run_mode: RunMode = typer.Option(RunMode.ONLINE_INFERENCE),
    use_chroma: bool = typer.Option(True),
    export_eval_scores: bool = typer.Option(True),
    promote_dry_run: bool = typer.Option(False),
    promote_high_risk_threshold: float = typer.Option(8.0, min=0.0, max=10.0),
    promote_hard_negative_threshold: float = typer.Option(2.5, min=0.0, max=10.0),
    promote_max_uncertainty: float = typer.Option(0.35, min=0.0, max=1.0),
    promote_min_evidence_tags: int = typer.Option(1, min=0),
    pattern_min_support: int = typer.Option(2, min=1),
    normal_label: int = typer.Option(0),
    video_fps: float = typer.Option(30.0),
) -> None:
    summary = run_workflow(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        baseline_metrics_dir=baseline_metrics_dir,
        stages=stage,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        promote_dry_run=promote_dry_run,
        promote_high_risk_threshold=promote_high_risk_threshold,
        promote_hard_negative_threshold=promote_hard_negative_threshold,
        promote_max_uncertainty=promote_max_uncertainty,
        promote_min_evidence_tags=promote_min_evidence_tags,
        pattern_min_support=pattern_min_support,
        normal_label=normal_label,
        video_fps=video_fps,
    )
    typer.echo(json.dumps(_json_safe(summary), indent=2))


if __name__ == "__main__":
    app()
