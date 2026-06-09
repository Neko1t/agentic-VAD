from __future__ import annotations

import importlib.util
import io
import json
import warnings
from contextlib import redirect_stdout
from pathlib import Path

import typer
from sklearn.exceptions import UndefinedMetricWarning

app = typer.Typer(
    add_completion=False,
    help="Run original temporal VAD ROC-AUC / PR-AUC evaluation on agentic-exported scores.",
)


def _load_original_eval_module():
    module_path = Path(__file__).resolve().parents[1] / "eval.py"
    spec = importlib.util.spec_from_file_location("agentic_original_eval", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load original eval module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_metric_report(metrics_dir: Path) -> dict[str, object]:
    report: dict[str, object] = {"metrics_dir": str(metrics_dir)}
    for metric_name in ("roc_auc", "pr_auc"):
        metric_path = metrics_dir / f"{metric_name}.txt"
        if not metric_path.exists():
            continue
        try:
            report[metric_name] = float(metric_path.read_text(encoding="utf-8").strip())
        except ValueError:
            report[metric_name] = metric_path.read_text(encoding="utf-8").strip()
    threshold_path = metrics_dir / "optimal_thresholds.txt"
    if threshold_path.exists():
        thresholds: dict[str, float | str] = {}
        for line in threshold_path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            try:
                thresholds[key.strip()] = float(value)
            except ValueError:
                thresholds[key.strip()] = value
        report["thresholds"] = thresholds
    return report


def run_metrics(
    *,
    root_path: Path,
    annotation_file_path: Path,
    temporal_annotation_file: Path,
    scores_dir: Path,
    captions_dir: Path,
    output_dir: Path,
    frame_interval: int = 16,
    normal_label: int = 0,
    video_fps: float = 30.0,
    quiet: bool = False,
) -> dict[str, object]:
    original_eval = _load_original_eval_module()
    if quiet:
        original_eval.tqdm = lambda iterable: iterable
        with redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore", UndefinedMetricWarning)
            original_eval.main(
                root_path=str(root_path),
                annotationfile_path=str(annotation_file_path),
                temporal_annotation_file=str(temporal_annotation_file),
                scores_dir=str(scores_dir),
                captions_dir=str(captions_dir),
                output_dir=str(output_dir),
                frame_interval=frame_interval,
                normal_label=normal_label,
                without_labels=False,
                visualize=False,
                video_fps=video_fps,
            )
    else:
        original_eval.main(
            root_path=str(root_path),
            annotationfile_path=str(annotation_file_path),
            temporal_annotation_file=str(temporal_annotation_file),
            scores_dir=str(scores_dir),
            captions_dir=str(captions_dir),
            output_dir=str(output_dir),
            frame_interval=frame_interval,
            normal_label=normal_label,
            without_labels=False,
            visualize=False,
            video_fps=video_fps,
        )
    report = load_metric_report(output_dir)
    report.update(
        {
            "scores_dir": str(scores_dir),
            "captions_dir": str(captions_dir),
            "frame_interval": frame_interval,
            "normal_label": normal_label,
            "video_fps": video_fps,
        }
    )
    return report


@app.command()
def main(
    root_path: Path = typer.Option(..., exists=True, file_okay=False),
    annotation_file_path: Path = typer.Option(..., exists=True, dir_okay=False),
    temporal_annotation_file: Path = typer.Option(..., exists=True, dir_okay=False),
    scores_dir: Path = typer.Option(..., exists=True, file_okay=False),
    captions_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs/metrics")),
    frame_interval: int = typer.Option(16, min=1),
    normal_label: int = typer.Option(0),
    video_fps: float = typer.Option(30.0),
) -> None:
    report = run_metrics(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        temporal_annotation_file=temporal_annotation_file,
        scores_dir=scores_dir,
        captions_dir=captions_dir,
        output_dir=output_dir,
        frame_interval=frame_interval,
        normal_label=normal_label,
        video_fps=video_fps,
    )
    typer.echo(json.dumps(report, indent=2))


if __name__ == "__main__":
    app()
