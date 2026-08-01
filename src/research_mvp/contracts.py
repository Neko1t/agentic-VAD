from __future__ import annotations

from dataclasses import dataclass
from typing import Any


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def _int64(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not INT64_MIN <= value <= INT64_MAX:
        raise ValueError(f"{name} must be signed int64")


@dataclass(frozen=True, slots=True)
class MvpInterval:
    start_us: int
    end_us: int

    def __post_init__(self) -> None:
        _int64(self.start_us, "start_us")
        _int64(self.end_us, "end_us")
        if self.start_us < 0 or self.end_us <= self.start_us:
            raise ValueError("interval must be non-empty [start_us,end_us)")

    @property
    def length_us(self) -> int:
        return self.end_us - self.start_us


@dataclass(frozen=True, slots=True)
class MvpEvidenceAtom:
    atom_id: str
    source_family: str
    status: str
    role: str
    direction: float
    validity_gate: int
    q_in: float
    q_src: float
    interval: MvpInterval
    fact_slot: tuple[str, str, str, str] | None = None
    interpretation_trace: str | None = None
    quality_policy: str = "MEASURED"


@dataclass(frozen=True, slots=True)
class MvpFactContradiction:
    left_atom_id: str
    right_atom_id: str
    score: float


@dataclass(frozen=True, slots=True)
class MvpObservedTemporalFact:
    fact_id: str
    interval: MvpInterval


@dataclass(frozen=True, slots=True)
class MvpEvidenceObservation:
    observation_id: str
    source: str
    channel: str
    family: str
    status: str
    q_in: float
    q_src: float
    direction: float
    observed_intervals: tuple[MvpInterval, ...]
    risk_atom_ids: tuple[str, ...] = ()
    fact_tokens: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None
    temporal_triples: tuple[tuple[str, str, str], ...] = ()
    atoms: tuple[MvpEvidenceAtom, ...] = ()
    fact_contradictions: tuple[MvpFactContradiction, ...] = ()
    temporal_facts: tuple[MvpObservedTemporalFact, ...] = ()


@dataclass(frozen=True, slots=True)
class MvpPacketAssessment:
    assessment_id: str
    observation_id: str
    channel: str
    family: str
    reliability: float
    direction: float
    observed_intervals: tuple[MvpInterval, ...]
    risk_atom_ids: tuple[str, ...] = ()
    atoms: tuple[MvpEvidenceAtom, ...] = ()


@dataclass(frozen=True, slots=True)
class MvpModalityEvidence:
    channel: str
    family: str
    positive: float
    negative: float
    quality: float
    direction: float
    observed_intervals: tuple[MvpInterval, ...]


@dataclass(frozen=True, slots=True)
class MvpB2Output:
    video_id: str
    window_id: str
    window_ordinal: int
    slot: str
    positive: float
    negative: float
    quality: float
    direction: float
    conflict: float
    e_local: float
    u_local: float
    modalities: tuple[MvpModalityEvidence, ...]
    assessment_ids: tuple[str, ...]
    direction_conflict: float = 0.0
    fact_conflict: float = 0.0
    supporting_atom_ids: tuple[str, ...] = ()
    counter_atom_ids: tuple[str, ...] = ()
    fact_conflict_pairs: tuple[tuple[str, str, float], ...] = ()
    fact_tokens: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None
    temporal_triples: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MvpAdvisoryPayload:
    case_id: str
    reliability: float
    consistency: float
    direction: float
    atom_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MvpRetrievalKey:
    case_id: str
    source_video_id: str
    scope: str
    key_hash: str
    payload_hash: str
    embedding: tuple[float, ...] | None
    tokens: tuple[str, ...]
    temporal_triples: tuple[tuple[str, str, str], ...]
    visible_from_window_ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class MvpRetrievalManifest:
    query_video_id: str
    query_window_id: str
    snapshot_payload_hash: str
    snapshot_version: int
    view_orders: tuple[tuple[str, tuple[str, ...]], ...]
    rrf_order: tuple[str, ...]
    ordered_top_k: tuple[str, ...]
    payload_hashes: tuple[tuple[str, str], ...]
    view_failures: tuple[tuple[str, str], ...] = ()
    accepted_ref: str | None = None
    accepted_file_hash: str | None = None


@dataclass(frozen=True, slots=True)
class MvpB6Output:
    e_commit: float
    reliability_commit: float
    direction_commit: float
    u_commit: float
    memory_status: str
    source_case_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MvpB4Commit:
    video_id: str
    window_id: str
    window_ordinal: int
    version_before: int
    version_after: int
    fast: float
    slow: float
    momentum: float
    z: float
    uncertainty: float
    lower: float
    upper: float
    state: str
    transition_reason: str


@dataclass(frozen=True, slots=True)
class MvpEpisode:
    episode_id: str
    video_id: str
    role: str
    ordinal: int
    core_window_ordinals: tuple[int, ...]
    member_window_ordinals: tuple[int, ...]
    closed: bool
    visible_from_window_ordinal: int


@dataclass(frozen=True, slots=True)
class MvpWindowArtifact:
    video_id: str
    window_id: str
    window_ordinal: int
    final_b2_payload_hash: str
    retrieval_manifest_payload_hash: str
    final_b6_payload_hash: str
    b4_payload_hash: str
    prediction: float
    memory_status: str


@dataclass(frozen=True, slots=True)
class MvpPredictionFreeze:
    video_id: str
    ordered_window_artifact_hashes: tuple[str, ...]
    ordered_prediction_payload_hashes: tuple[str, ...]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class MvpMemorySnapshot:
    namespace_id: str
    version: int
    previous_snapshot_payload_hash: str | None
    last_committed_video_id: str | None
    prediction_freeze_hash: str | None
    cases: tuple[dict[str, Any], ...]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class MvpOutputHashManifest:
    attempt_id: str
    entries: tuple[dict[str, Any], ...]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class MvpMemoryFreeze:
    namespace_id: str
    snapshot_payload_hash: str
    snapshot_file_hash: str
    version: int


@dataclass(frozen=True, slots=True)
class MvpInferenceFreeze:
    attempt_id: str
    prediction_freeze_hashes: tuple[str, ...]
    output_manifest_hash: str
    memory_freeze_hash: str


@dataclass(frozen=True, slots=True)
class MvpEvaluatorLaunchPlan:
    attempt_id: str
    evaluation_attempt_id: str
    inference_freeze_hash: str
    annotation_manifest_ref: str
    readable_refs: tuple[str, ...]
    allowed_inputs: tuple[dict[str, Any], ...]
    metrics_ref: str
    receipt_ref: str
    runtime_profile: str
    research_claim_status: str


@dataclass(frozen=True, slots=True)
class MvpEvaluationReceipt:
    status_code: str
    metrics_ref: str
    metrics_hash: str
    receipt_ref: str
    receipt_hash: str
    process_exit_code: int
