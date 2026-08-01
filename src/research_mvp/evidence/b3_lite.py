from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..contracts import MvpB2Output, MvpEvidenceObservation, MvpInterval, MvpPacketAssessment
from ..math.numeric import divide, multiply, subtract
from ..math.b2 import build_b2_output
from .adapters import MvpAdapterResult, PrecomputedEvidenceAdapter


ACTION_ORDER = ("OCR", "AUDIO")
MAX_ACTIONS = 2


@dataclass(frozen=True, slots=True)
class MvpToolTrace:
    action: str
    status: str
    raw_payload_hash: str | None
    failure_code: str | None
    eligibility_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MvpB3LiteResult:
    final_b2: MvpB2Output
    b2_outputs: tuple[MvpB2Output, ...]
    attempted_actions: tuple[str, ...]
    accepted_actions: tuple[str, ...]
    observations: tuple[MvpEvidenceObservation, ...]
    assessments: tuple[MvpPacketAssessment, ...]
    tool_trace: tuple[MvpToolTrace, ...]
    stop_reason: str


def _metadata(
    observations: tuple[MvpEvidenceObservation, ...],
) -> tuple[
    tuple[str, ...],
    tuple[float, ...] | None,
    tuple[tuple[str, str, str], ...],
    tuple[Any, ...],
]:
    ordered = tuple(sorted(observations, key=lambda item: item.observation_id.encode("utf-8")))
    tokens = tuple(sorted({token for item in ordered for token in item.fact_tokens}, key=lambda value: value.encode("utf-8")))
    embeddings = tuple(item.embedding for item in ordered if item.embedding is not None)
    embedding = embeddings[0] if embeddings else None
    triples = tuple(sorted({triple for item in ordered for triple in item.temporal_triples}))
    contradictions = tuple(
        contradiction
        for item in ordered
        for contradiction in item.fact_contradictions
    )
    return tokens, embedding, triples, contradictions


def _build(
    video_id: str,
    window_id: str,
    window_ordinal: int,
    window: MvpInterval,
    observations: tuple[MvpEvidenceObservation, ...],
    assessments: tuple[MvpPacketAssessment, ...],
    slot: str,
) -> MvpB2Output:
    tokens, embedding, triples, contradictions = _metadata(observations)
    return build_b2_output(
        video_id,
        window_id,
        window_ordinal,
        window,
        assessments,
        slot=slot,
        fact_contradictions=contradictions,
        fact_tokens=tokens,
        embedding=embedding,
        temporal_triples=triples,
    )


def _coverage_ratio(window: MvpInterval, observations: tuple[MvpEvidenceObservation, ...]) -> float:
    clipped: list[tuple[int, int]] = []
    for observation in observations:
        for interval in observation.observed_intervals:
            start = max(window.start_us, interval.start_us)
            end = min(window.end_us, interval.end_us)
            if end > start:
                clipped.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(clipped):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    covered_us = sum(end - start for start, end in merged)
    return divide(float(covered_us), float(window.length_us))


def _eligibility_reasons(
    *,
    action: str,
    required_actions: tuple[str, ...],
    observations: tuple[MvpEvidenceObservation, ...],
    current_b2: MvpB2Output,
    window: MvpInterval,
) -> tuple[str, ...]:
    expected_channel = "OCR" if action == "OCR" else "ACOUSTIC_EVENT"
    if any(observation.channel == expected_channel for observation in observations):
        return ()
    reasons: list[str] = []
    if action in required_actions:
        reasons.append("MISSING_CAPABILITY")
    if _coverage_ratio(window, observations) < 1.0:
        reasons.append("OBSERVED_COVERAGE_GAP")
    observed_reliability = max(
        (multiply(observation.q_in, observation.q_src) for observation in observations),
        default=0.0,
    )
    reliability = multiply(observed_reliability, subtract(1.0, current_b2.conflict))
    if reliability < 1.0:
        reasons.append("RELIABILITY_GAP")
    return tuple(reasons)


def run_b3_lite(
    *,
    video_id: str,
    window_id: str,
    window_ordinal: int,
    window: MvpInterval,
    base_results: tuple[MvpAdapterResult, ...],
    action_artifacts: Mapping[str, tuple[Mapping[str, Any] | None, str | None]],
    adapter: PrecomputedEvidenceAdapter,
    required_actions: tuple[str, ...] = (),
) -> MvpB3LiteResult:
    if len(required_actions) != len(set(required_actions)) or any(action not in ACTION_ORDER for action in required_actions):
        raise ValueError("required actions must be a unique subset of the frozen registry")
    observations = tuple(result.observation for result in base_results if result.accepted and result.observation is not None)
    assessments = tuple(result.assessment for result in base_results if result.accepted and result.assessment is not None)
    if len(observations) != len(assessments):
        raise ValueError("accepted observation and assessment counts differ")
    outputs: list[MvpB2Output] = [
        _build(video_id, window_id, window_ordinal, window, observations, assessments, "B2:base")
    ]
    attempted: list[str] = []
    accepted: list[str] = []
    traces: list[MvpToolTrace] = []
    stop_reason = "GAPS_CLOSED"

    while len(attempted) < MAX_ACTIONS:
        current_b2 = outputs[-1]
        eligible = tuple(
            (action, reasons)
            for action in ACTION_ORDER
            if action not in attempted
            if (
                reasons := _eligibility_reasons(
                    action=action,
                    required_actions=required_actions,
                    observations=observations,
                    current_b2=current_b2,
                    window=window,
                )
            )
        )
        if not eligible:
            stop_reason = "GAPS_CLOSED"
            break
        action, reasons = eligible[0]
        action_index = len(attempted)
        attempted.append(action)
        raw, expected_hash = action_artifacts.get(action, (None, None))
        result = adapter.accept(action, raw, expected_hash)
        traces.append(
            MvpToolTrace(
                action=action,
                status="ACCEPTED" if result.accepted else "UNAVAILABLE",
                raw_payload_hash=result.raw_payload_hash,
                failure_code=None if result.failure is None else result.failure.code,
                eligibility_reasons=reasons,
            )
        )
        if not result.accepted:
            continue
        if result.observation is None or result.assessment is None:
            raise ValueError("accepted adapter result is incomplete")
        observations = (*observations, result.observation)
        assessments = (*assessments, result.assessment)
        accepted.append(action)
        outputs.append(
            _build(
                video_id,
                window_id,
                window_ordinal,
                window,
                observations,
                assessments,
                f"B2:step-{action_index:03d}",
            )
        )
    else:
        stop_reason = "BUDGET_EXHAUSTED"

    final_b2 = _build(video_id, window_id, window_ordinal, window, observations, assessments, "B2:final")
    outputs.append(final_b2)
    return MvpB3LiteResult(
        final_b2=final_b2,
        b2_outputs=tuple(outputs),
        attempted_actions=tuple(attempted),
        accepted_actions=tuple(accepted),
        observations=tuple(observations),
        assessments=tuple(assessments),
        tool_trace=tuple(traces),
        stop_reason=stop_reason,
    )
