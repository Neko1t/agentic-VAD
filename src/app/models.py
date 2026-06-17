from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.core.schemas import RunMode


class WorkflowType(str, Enum):
    MINI = "mini"
    FULL = "full"
    STAGE = "stage"


class CheckStatus(BaseModel):
    name: str
    ready: bool
    level: Literal["ok", "warn", "error"]
    message: str
    fix_hint: str | None = None
    path: str | None = None


class ProjectStatusSnapshot(BaseModel):
    ready: bool
    checks: list[CheckStatus] = Field(default_factory=list)
    root_path: Path
    annotation_file_path: Path
    captions_dir: Path
    temporal_annotation_file: Path | None = None
    baseline_scores_dir: Path | None = None
    output_dir: Path | None = None


class RunRequest(BaseModel):
    workflow_type: WorkflowType
    root_path: Path
    annotation_file_path: Path
    captions_dir: Path
    output_dir: Path = Field(default=Path("./data/agentic_outputs"))
    memory_dir: Path = Field(default=Path("./data/agentic_memory"))
    temporal_annotation_file: Path | None = None
    baseline_scores_dir: Path | None = None
    baseline_metrics_dir: Path | None = None
    stage_names: list[str] = Field(default_factory=list)
    frame_interval: int = Field(default=16, ge=1)
    rolling_window_size: int = Field(default=4, ge=1)
    use_audio: bool = False
    use_ocr: bool = False
    top_k: int = Field(default=5, ge=1)
    run_mode: RunMode = RunMode.ONLINE_INFERENCE
    use_chroma: bool = True
    export_eval_scores: bool = True
    normal_label: int = 0
    video_fps: float = 30.0
    gpu_device: str | None = None
    use_vlm: bool = False
    video_root_path: Path | None = None
    vlm_model_path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultSummary(BaseModel):
    run_root: Path
    workflow_summary_path: Path | None = None
    comparison_report_path: Path | None = None
    workflow_summary: Optional[dict[str, Any]] = None
    comparison_report: Optional[dict[str, Any]] = None
