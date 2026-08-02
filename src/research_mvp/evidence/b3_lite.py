from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from ..codec import payload_hash
from ..contracts import MvpB2Output, MvpEvidenceObservation, MvpInterval, MvpPacketAssessment
from ..math.numeric import divide, multiply, numeric_equal, subtract
from ..math.b2 import build_b2_output
from .adapters import MvpAdapterResult, PrecomputedEvidenceAdapter


ACTION_ORDER = ("OCR", "AUDIO")
MAX_ACTIONS = 2


@dataclass(frozen=True, slots=True)
class MvpB3EligibilityAudit:
    iteration: int
    action: str
    coverage_threshold: float
    observed_coverage: float
    reliability_threshold: float
    observed_reliability: float
    conflict: float
    effective_reliability: float
    reasons: tuple[str, ...]
    selected: bool
    decision: str


@dataclass(frozen=True, slots=True)
class MvpB2StageDelta:
    before_payload_hash: str
    after_payload_hash: str
    before_positive: float
    after_positive: float
    delta_positive: float
    before_negative: float
    after_negative: float
    delta_negative: float
    before_quality: float
    after_quality: float
    delta_quality: float
    before_direction: float
    after_direction: float
    delta_direction: float
    before_conflict: float
    after_conflict: float
    delta_conflict: float
    before_e_local: float
    after_e_local: float
    delta_e_local: float
    before_u_local: float
    after_u_local: float
    delta_u_local: float


@dataclass(frozen=True, slots=True)
class MvpToolTrace:
    action: str
    status: str
    accepted: bool
    informative: bool
    contributed: bool
    raw_payload_hash: str | None
    failure_code: str | None
    eligibility_reasons: tuple[str, ...]
    b2_delta: MvpB2StageDelta | None


@dataclass(frozen=True, slots=True)
class MvpB3LiteResult:
    final_b2: MvpB2Output
    b2_outputs: tuple[MvpB2Output, ...]
    attempted_actions: tuple[str, ...]
    accepted_actions: tuple[str, ...]
    observations: tuple[MvpEvidenceObservation, ...]
    assessments: tuple[MvpPacketAssessment, ...]
    eligibility_audits: tuple[MvpB3EligibilityAudit, ...]
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


def _eligibility_audit(
    *,
    iteration: int,
    action: str,
    required_actions: tuple[str, ...],
    observations: tuple[MvpEvidenceObservation, ...],
    current_b2: MvpB2Output,
    window: MvpInterval,
) -> MvpB3EligibilityAudit:
    expected_channel = "OCR" if action == "OCR" else "ACOUSTIC_EVENT"
    already_present = any(observation.channel == expected_channel for observation in observations)
    observed_coverage = _coverage_ratio(window, observations)
    observed_reliability = max(
        (multiply(observation.q_in, observation.q_src) for observation in observations),
        default=0.0,
    )
    reliability = multiply(observed_reliability, subtract(1.0, current_b2.conflict))
    reasons: list[str] = []
    if not already_present and action in required_actions:
        reasons.append("MISSING_CAPABILITY")
    if not already_present and observed_coverage < 1.0:
        reasons.append("OBSERVED_COVERAGE_GAP")
    if not already_present and reliability < 1.0:
        reasons.append("RELIABILITY_GAP")
    return MvpB3EligibilityAudit(
        iteration=iteration,
        action=action,
        coverage_threshold=1.0,
        observed_coverage=observed_coverage,
        reliability_threshold=1.0,
        observed_reliability=observed_reliability,
        conflict=current_b2.conflict,
        effective_reliability=reliability,
        reasons=tuple(reasons),
        selected=False,
        decision="INELIGIBLE",
    )


def _stage_delta(before: MvpB2Output, after: MvpB2Output) -> MvpB2StageDelta:
    return MvpB2StageDelta(
        before_payload_hash=payload_hash(asdict(before)),
        after_payload_hash=payload_hash(asdict(after)),
        before_positive=before.positive,
        after_positive=after.positive,
        delta_positive=subtract(after.positive, before.positive),
        before_negative=before.negative,
        after_negative=after.negative,
        delta_negative=subtract(after.negative, before.negative),
        before_quality=before.quality,
        after_quality=after.quality,
        delta_quality=subtract(after.quality, before.quality),
        before_direction=before.direction,
        after_direction=after.direction,
        delta_direction=subtract(after.direction, before.direction),
        before_conflict=before.conflict,
        after_conflict=after.conflict,
        delta_conflict=subtract(after.conflict, before.conflict),
        before_e_local=before.e_local,
        after_e_local=after.e_local,
        delta_e_local=subtract(after.e_local, before.e_local),
        before_u_local=before.u_local,
        after_u_local=after.u_local,
        delta_u_local=subtract(after.u_local, before.u_local),
    )


def _informative(result: MvpAdapterResult) -> bool:
    if not result.accepted or result.observation is None:
        return False
    if not numeric_equal(result.observation.direction, 0.0):
        return True
    return any(
        atom.status == "VALID"
        and atom.role == "RISK"
        and atom.validity_gate == 1
        and not numeric_equal(atom.direction, 0.0)
        for atom in result.observation.atoms
    )


def _contributed(delta: MvpB2StageDelta) -> bool:
    return any(
        not numeric_equal(value, 0.0)
        for value in (
            delta.delta_positive,
            delta.delta_negative,
            delta.delta_quality,
            delta.delta_direction,
            delta.delta_conflict,
            delta.delta_e_local,
            delta.delta_u_local,
        )
    )


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
    eligibility_audits: list[MvpB3EligibilityAudit] = []
    traces: list[MvpToolTrace] = []
    stop_reason = "GAPS_CLOSED"

    while len(attempted) < MAX_ACTIONS:
        current_b2 = outputs[-1]
        evaluated = tuple(
            _eligibility_audit(
                iteration=len(attempted),
                action=action,
                required_actions=required_actions,
                observations=observations,
                current_b2=current_b2,
                window=window,
            )
            for action in ACTION_ORDER
            if action not in attempted
        )
        eligible = tuple(audit for audit in evaluated if audit.reasons)
        if not eligible:
            eligibility_audits.extend(replace(audit, decision="STOP_GAPS_CLOSED") for audit in evaluated)
            stop_reason = "GAPS_CLOSED"
            break
        selected = eligible[0]
        action = selected.action
        reasons = selected.reasons
        eligibility_audits.extend(
            replace(
                audit,
                selected=audit.action == action,
                decision="SELECT" if audit.action == action else "DEFER_ACTION_ORDER" if audit.reasons else "INELIGIBLE",
            )
            for audit in evaluated
        )
        action_index = len(attempted)
        attempted.append(action)
        raw, expected_hash = action_artifacts.get(action, (None, None))
        result = adapter.accept(action, raw, expected_hash)
        if not result.accepted:
            traces.append(
                MvpToolTrace(
                    action=action,
                    status="UNAVAILABLE",
                    accepted=False,
                    informative=False,
                    contributed=False,
                    raw_payload_hash=result.raw_payload_hash,
                    failure_code=None if result.failure is None else result.failure.code,
                    eligibility_reasons=reasons,
                    b2_delta=None,
                )
            )
            continue
        if result.observation is None or result.assessment is None:
            raise ValueError("accepted adapter result is incomplete")
        observations = (*observations, result.observation)
        assessments = (*assessments, result.assessment)
        accepted.append(action)
        step_b2 = _build(
            video_id,
            window_id,
            window_ordinal,
            window,
            observations,
            assessments,
            f"B2:step-{action_index:03d}",
        )
        delta = _stage_delta(current_b2, step_b2)
        traces.append(
            MvpToolTrace(
                action=action,
                status="ACCEPTED",
                accepted=True,
                informative=_informative(result),
                contributed=_contributed(delta),
                raw_payload_hash=result.raw_payload_hash,
                failure_code=None,
                eligibility_reasons=reasons,
                b2_delta=delta,
            )
        )
        outputs.append(step_b2)
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
        eligibility_audits=tuple(eligibility_audits),
        tool_trace=tuple(traces),
        stop_reason=stop_reason,
    )
