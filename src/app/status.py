from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path

from src.app.models import CheckStatus, ProjectStatusSnapshot


def _check_path(name: str, path: Path, *, kind: str = "path", required: bool = True) -> CheckStatus:
    exists = path.exists()
    if exists:
        return CheckStatus(
            name=name,
            ready=True,
            level="ok",
            message=f"{kind} exists",
            path=str(path),
        )
    level = "error" if required else "warn"
    return CheckStatus(
        name=name,
        ready=False,
        level=level,
        message=f"missing {kind}",
        fix_hint=f"Prepare {path}",
        path=str(path),
    )


def _check_python_package(import_name: str, label: str) -> CheckStatus:
    spec = importlib.util.find_spec(import_name)
    if spec is not None:
        return CheckStatus(name=label, ready=True, level="ok", message="package importable")
    return CheckStatus(
        name=label,
        ready=False,
        level="warn",
        message="package not importable",
        fix_hint=f"Install dependency for {label}",
    )


def build_status_snapshot(
    *,
    root_path: Path,
    annotation_file_path: Path,
    captions_dir: Path,
    temporal_annotation_file: Path | None = None,
    baseline_scores_dir: Path | None = None,
    output_dir: Path | None = None,
) -> ProjectStatusSnapshot:
    checks: list[CheckStatus] = []

    checks.append(
        CheckStatus(
            name="python",
            ready=True,
            level="ok",
            message=f"python={os.sys.version.split()[0]}",
        )
    )
    checks.append(
        CheckStatus(
            name="conda_env",
            ready=bool(os.environ.get("CONDA_DEFAULT_ENV")),
            level="ok" if os.environ.get("CONDA_DEFAULT_ENV") else "warn",
            message=os.environ.get("CONDA_DEFAULT_ENV", "conda env not detected"),
        )
    )
    checks.append(_check_python_package("typer", "typer"))
    checks.append(_check_python_package("rich", "rich"))

    checks.append(_check_path("frames_root", root_path, kind="directory"))
    checks.append(_check_path("annotation_file", annotation_file_path, kind="file"))
    checks.append(_check_path("captions_dir", captions_dir, kind="directory"))
    if temporal_annotation_file is not None:
        checks.append(_check_path("temporal_annotation_file", temporal_annotation_file, kind="file"))
    if baseline_scores_dir is not None:
        checks.append(_check_path("baseline_scores_dir", baseline_scores_dir, kind="directory", required=False))
    if output_dir is not None:
        checks.append(
            CheckStatus(
                name="output_dir",
                ready=True,
                level="ok",
                message="output directory will be created if missing",
                path=str(output_dir),
            )
        )

    ready = all(check.ready or check.level == "warn" for check in checks) and not any(
        check.level == "error" for check in checks
    )

    return ProjectStatusSnapshot(
        ready=ready,
        checks=checks,
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        temporal_annotation_file=temporal_annotation_file,
        baseline_scores_dir=baseline_scores_dir,
        output_dir=output_dir,
    )


def build_workspace_snapshot(*, repo_root: Path, preferred_dataset: str = "ucf_crime") -> dict[str, object]:
    data_root = repo_root / "data"
    preferred_root = data_root / preferred_dataset
    mini_root = data_root / f"{preferred_dataset}_mini"

    def _dataset_ready(dataset_root: Path) -> bool:
        required = (
            dataset_root / "frames",
            dataset_root / "annotations" / "test.txt",
            dataset_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
            dataset_root / "captions" / "video_llama3_json_results",
        )
        return all(path.exists() for path in required)

    model_targets = [
        ("embedding", repo_root / "libs" / "embeddings" / "bge-base-en-v1.5", repo_root / ".asset_status" / "bge-base-en-v1.5.done"),
        ("vlm", repo_root / "libs" / "videollama3" / "VideoLLaMA3-7B", repo_root / ".asset_status" / "videollama3-7b.done"),
        ("llm", repo_root / "libs" / "llama" / "llama3.1-8b", repo_root / ".asset_status" / "llama-3.1-8b-instruct.done"),
    ]
    models = [
        {
            "name": name,
            "path": str(path),
            "ready": path.exists() or marker.exists(),
            "marker": str(marker),
        }
        for name, path, marker in model_targets
    ]
    datasets = [
        {"name": preferred_dataset, "ready": _dataset_ready(preferred_root), "path": str(preferred_root)},
        {"name": f"{preferred_dataset}_mini", "ready": _dataset_ready(mini_root), "path": str(mini_root)},
    ]

    required_actions: list[str] = []
    if not any(item["ready"] for item in models):
        required_actions.append("download at least one required model asset")
    if not datasets[1]["ready"]:
        required_actions.append("prepare the mini dataset for a smoke experiment")
    if not datasets[0]["ready"]:
        required_actions.append("prepare the full dataset for complete experiments")

    recent_result = None
    output_root = data_root / "agentic_outputs"
    if output_root.exists():
        comparison_candidates = sorted(output_root.rglob("comparison_report.json"), reverse=True)
        if comparison_candidates:
            comparison_path = comparison_candidates[0]
            workflow_path = comparison_path.parent / "workflow_summary.json"
            comparison_payload = json.loads(comparison_path.read_text(encoding="utf-8"))
            workflow_payload = None
            if workflow_path.exists():
                workflow_payload = json.loads(workflow_path.read_text(encoding="utf-8"))
            recent_result = {
                "path": str(comparison_path.parent),
                "status": comparison_payload.get("status"),
                "summary": f"latest comparison at {comparison_path.parent.name}",
                "comparison": comparison_payload,
                "workflow": workflow_payload,
            }

    return {
        "preferred_dataset": preferred_dataset,
        "mini_ready": datasets[1]["ready"],
        "full_ready": datasets[0]["ready"],
        "models": models,
        "datasets": datasets,
        "required_actions": required_actions,
        "recent_result": recent_result,
    }


def build_repl_overview(*, repo_root: Path, preferred_dataset: str = "ucf_crime") -> dict[str, object]:
    workspace = build_workspace_snapshot(repo_root=repo_root, preferred_dataset=preferred_dataset)
    recommended_commands: list[str] = []
    missing_items: list[str] = []

    if not any(item["ready"] for item in workspace["models"]):
        missing_items.append("core model assets are missing")
        recommended_commands.append("python agentic_vad.py assets download --preset models-core")

    if not workspace["mini_ready"]:
        missing_items.append("mini dataset is not ready")
        recommended_commands.append("python agentic_vad.py dataset build-mini")
    else:
        recommended_commands.append("run mini")

    if workspace["full_ready"]:
        recommended_commands.append("run full")
    else:
        missing_items.append("full dataset is not ready")

    return {
        "preferred_dataset": preferred_dataset,
        "mini_ready": workspace["mini_ready"],
        "full_ready": workspace["full_ready"],
        "models": workspace["models"],
        "datasets": workspace["datasets"],
        "missing_items": missing_items,
        "recommended_commands": recommended_commands,
        "recent_result": workspace.get("recent_result"),
    }
