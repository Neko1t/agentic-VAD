from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunMode(str, Enum):
    OFFLINE_EVAL = "offline_eval"
    ONLINE_INFERENCE = "online_inference"
    MEMORY_BUILDING = "memory_building"
    DEBUG_REPLAY = "debug_replay"


class MemoryWriteDecision(str, Enum):
    WRITE = "write"
    SKIP = "skip"
    UPDATE_EXISTING = "update_existing"


class MemoryCaseType(str, Enum):
    HIGH_RISK = "high_risk"
    HARD_NEGATIVE = "hard_negative"
    AMBIGUOUS = "ambiguous"
    ROUTINE = "routine"


class ToolCallRecord(BaseModel):
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    error: Optional[str] = None
    artifact_refs: List[str] = Field(default_factory=list)


class TimeSpan(BaseModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    start_time: Optional[float] = Field(default=None, ge=0.0)
    end_time: Optional[float] = Field(default=None, ge=0.0)


class WindowInput(BaseModel):
    video_id: str
    video_path: str
    window_id: str
    time_span: TimeSpan
    frame_indices: List[int] = Field(default_factory=list)
    audio_path: Optional[str] = None
    frame_paths: List[str] = Field(default_factory=list)


class ModalityConfidence(BaseModel):
    vision_conf: float = Field(default=1.0, ge=0.0, le=1.0)
    audio_conf: float = Field(default=0.0, ge=0.0, le=1.0)
    ocr_conf: float = Field(default=0.0, ge=0.0, le=1.0)


class ObservationCard(BaseModel):
    video_id: str
    window_id: str
    time_span: TimeSpan
    vision_caption: str = ""
    entities: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    scene_context: str = ""
    audio_events: List[str] = Field(default_factory=list)
    ocr_texts: List[str] = Field(default_factory=list)
    modality_confidence: ModalityConfidence = Field(default_factory=ModalityConfidence)
    score_raw: float = Field(default=0.0, ge=0.0, le=10.0)
    score_weighted: float = Field(default=0.0, ge=0.0, le=10.0)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_trace: List[str] = Field(default_factory=list)
    tool_trace: List[ToolCallRecord] = Field(default_factory=list)


class RollingSummaryState(BaseModel):
    video_id: str
    current_scene: str = ""
    active_entities: List[str] = Field(default_factory=list)
    event_chain: List[str] = Field(default_factory=list)
    risk_evolution: List[float] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    evidence_highlights: List[str] = Field(default_factory=list)


class RetrievedCase(BaseModel):
    case_id: str
    video_id: str
    score: float
    episode_summary: str
    action_sequence: str
    risk_score: float
    evidence_tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EpisodeSummary(BaseModel):
    video_id: str
    segment_span: TimeSpan
    story_text: str
    action_sequence: str
    risk_hints: List[str] = Field(default_factory=list)
    retrieved_case_ids: List[str] = Field(default_factory=list)
    matched_pattern_ids: List[str] = Field(default_factory=list)
    score_story: float = Field(default=0.0, ge=0.0, le=10.0)
    score_memory_adjusted: float = Field(default=0.0, ge=0.0, le=10.0)


class DecisionSegment(BaseModel):
    segment_span: TimeSpan
    score: float = Field(ge=0.0, le=10.0)
    explanation: str


class DecisionReport(BaseModel):
    video_id: str
    abnormal_segments: List[DecisionSegment] = Field(default_factory=list)
    segment_scores: List[float] = Field(default_factory=list)
    video_level_score: float = Field(default=0.0, ge=0.0, le=10.0)
    top_evidence: List[str] = Field(default_factory=list)
    retrieved_cases: List[str] = Field(default_factory=list)
    matched_patterns: List[str] = Field(default_factory=list)
    final_explanation: str = ""


class CaseMemoryRecord(BaseModel):
    case_id: str
    video_id: str
    time_span: TimeSpan
    label: str = "unknown"
    risk_score: float = Field(ge=0.0, le=10.0)
    episode_summary: str
    action_sequence: str
    key_entities: List[str] = Field(default_factory=list)
    scene_type: str = ""
    evidence_tags: List[str] = Field(default_factory=list)
    outcome: str = ""
    embedding_text: str
    provisional: bool = True
    case_type: MemoryCaseType = MemoryCaseType.AMBIGUOUS
    source: str = "online_inference"
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    local_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    final_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    retrieval_case_ids: List[str] = Field(default_factory=list)
    matched_pattern_ids: List[str] = Field(default_factory=list)
    hit_count: int = Field(default=1, ge=1)


class PatternMemoryRecord(BaseModel):
    pattern_id: str
    pattern_name: str
    prototype_action_sequence: str
    scene_constraints: List[str] = Field(default_factory=list)
    risk_level: float = Field(ge=0.0, le=10.0)
    supporting_cases: List[str] = Field(default_factory=list)
    counter_examples: List[str] = Field(default_factory=list)
    rule_text: str


class RetrievalQuery(BaseModel):
    video_id: Optional[str] = None
    action_sequence: str
    evidence_tags: List[str] = Field(default_factory=list)
    scene_type: str = ""
    story_text: str = ""


class RetrievalResult(BaseModel):
    similar_cases: List[RetrievedCase] = Field(default_factory=list)
    matched_patterns: List[PatternMemoryRecord] = Field(default_factory=list)
    retrieval_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CalibrationResult(BaseModel):
    score_local: float = Field(ge=0.0, le=10.0)
    score_story: float = Field(ge=0.0, le=10.0)
    score_memory_adjusted: float = Field(ge=0.0, le=10.0)
    final_score: float = Field(ge=0.0, le=10.0)
    calibration_reason: List[str] = Field(default_factory=list)


class MemoryWriteEvent(BaseModel):
    decision: MemoryWriteDecision
    case_type: Optional[MemoryCaseType] = None
    reason: str = ""
    skip_codes: List[str] = Field(default_factory=list)
    case_record: Optional[CaseMemoryRecord] = None
    duplicate_of: Optional[str] = None
    similarity_to_existing: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class StoryMemoryInput(BaseModel):
    video_id: str
    state: RollingSummaryState
    recent_observations: List[ObservationCard]
    top_k: int = Field(default=5, ge=1)
    run_mode: RunMode = RunMode.ONLINE_INFERENCE


class StoryMemoryResult(BaseModel):
    video_id: str
    episode: EpisodeSummary
    state: RollingSummaryState
    retrieval: RetrievalResult
    calibration: CalibrationResult
    memory_event: Optional[MemoryWriteEvent] = None
    disagreement_score: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction_flags: List[str] = Field(default_factory=list)
    tool_trace: List[ToolCallRecord] = Field(default_factory=list)
