from __future__ import annotations

from typing import Iterable

from src.app.models import RunRequest
from src.pipelines.run_agentic_workflow import WorkflowStage, resolve_stages


def resolve_workflow_stages(request: RunRequest) -> list[WorkflowStage]:
    requested: Iterable[WorkflowStage] | None
    if request.stage_names:
        requested = [WorkflowStage(name) for name in request.stage_names]
    else:
        requested = None
    return resolve_stages(
        requested,
        baseline_scores_dir=request.baseline_scores_dir,
        baseline_metrics_dir=request.baseline_metrics_dir,
    )
