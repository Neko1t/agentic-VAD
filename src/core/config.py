from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.core.schemas import RunMode


class MemoryConfig(BaseModel):
    storage_dir: Path = Field(default=Path("./data/agentic_memory"))
    case_collection_name: str = Field(default="case_memory")
    provisional_collection_name: str = Field(default="provisional_case_memory")
    pattern_file_name: str = Field(default="pattern_memory.jsonl")
    embedding_model_name: str = Field(default="BAAI/bge-base-en-v1.5")
    use_chroma: bool = Field(default=True)
    use_session_memory: bool = Field(default=True)
    top_k: int = Field(default=5, ge=1)


class ScoringConfig(BaseModel):
    local_score_threshold: float = Field(default=6.0, ge=0.0, le=10.0)
    segment_score_threshold: float = Field(default=6.5, ge=0.0, le=10.0)
    provisional_score_threshold: float = Field(default=7.0, ge=0.0, le=10.0)
    vision_prior: float = Field(default=0.65, ge=0.0, le=1.0)
    audio_prior: float = Field(default=0.20, ge=0.0, le=1.0)
    ocr_prior: float = Field(default=0.15, ge=0.0, le=1.0)


class PipelineConfig(BaseModel):
    root_path: Path
    annotation_file_path: Path
    captions_dir: Path
    output_dir: Path = Field(default=Path("./data/agentic_outputs"))
    frame_interval: int = Field(default=16, ge=1)
    rolling_window_size: int = Field(default=4, ge=1)
    use_audio: bool = Field(default=False)
    use_ocr: bool = Field(default=False)
    audio_backend: Optional[str] = Field(default=None)
    ocr_backend: Optional[str] = Field(default=None)
    run_mode: RunMode = Field(default=RunMode.ONLINE_INFERENCE)
    gpu_device: str
    runtime_device: str = Field(default="cuda:0")
    use_vlm: bool = Field(default=False)
    video_root_path: Optional[Path] = Field(default=None)
    vlm_model_path: Optional[Path] = Field(default=None)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.memory.storage_dir.mkdir(parents=True, exist_ok=True)
