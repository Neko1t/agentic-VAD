from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from ..contracts import MvpAdvisoryPayload, MvpB2Output, MvpB6Output
from .numeric import (
    add,
    compare,
    divide,
    multiply,
    ordered_sum,
    require_signed_unit,
    require_unit,
    strict_greater,
    subtract,
)


@dataclass(frozen=True, slots=True)
class MvpMemoryMass:
    positive: float
    negative: float
    quality: float
    direction: float
    conflict: float
    evidence: float
    reliability: float
    uncertainty: float
    weights: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MvpB6Audit:
    mode: str
    memory_enabled: bool
    local_evidence: float
    local_reliability: float
    local_direction: float
    local_uncertainty: float
    source_case_ids: tuple[str, ...]
    memory_positive: float
    memory_negative: float
    memory_quality: float
    memory_direction: float
    memory_conflict: float
    memory_evidence: float
    memory_reliability: float
    memory_uncertainty: float
    memory_weights: tuple[float, ...]
    memory_gate: float
    candidate_evidence: float
    candidate_reliability: float
    candidate_direction: float
    candidate_uncertainty: float
    abstained: bool
    output_evidence: float
    output_reliability: float
    output_direction: float
    output_uncertainty: float
    output_status: str


@dataclass(frozen=True, slots=True)
class MvpB6DetailedResult:
    output: MvpB6Output
    audit: MvpB6Audit


def _local(local: MvpB2Output) -> tuple[float, float, float, float]:
    reliability = require_unit(multiply(local.quality, subtract(1.0, local.conflict)), "local reliability")
    direction = require_signed_unit(local.direction, "local direction")
    evidence = require_signed_unit(multiply(reliability, direction), "local evidence")
    uncertainty = require_unit(subtract(1.0, abs(evidence)), "local uncertainty")
    return reliability, direction, evidence, uncertainty


def identity_b6(local: MvpB2Output, status: str) -> MvpB6Output:
    reliability, direction, evidence, uncertainty = _local(local)
    return MvpB6Output(
        e_commit=evidence,
        reliability_commit=reliability,
        direction_commit=direction,
        u_commit=uncertainty,
        memory_status=status,
    )


def memory_mass(ordered_cases: Iterable[MvpAdvisoryPayload]) -> MvpMemoryMass:
    cases = tuple(ordered_cases)
    if not cases:
        return MvpMemoryMass(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, ())
    harmonic = ordered_sum(divide(1.0, float(rank)) for rank in range(1, len(cases) + 1))
    weights = tuple(divide(divide(1.0, float(rank)), harmonic) for rank in range(1, len(cases) + 1))
    positive_parts: list[float] = []
    negative_parts: list[float] = []
    for weight, case in zip(weights, cases, strict=True):
        reliability = require_unit(case.reliability, "case reliability")
        consistency = require_unit(case.consistency, "case consistency")
        direction = require_signed_unit(case.direction, "case direction")
        base = multiply(multiply(weight, reliability), consistency)
        positive_parts.append(multiply(base, max(direction, 0.0)))
        negative_parts.append(multiply(base, max(-direction, 0.0)))
    positive = require_unit(ordered_sum(positive_parts), "memory positive")
    negative = require_unit(ordered_sum(negative_parts), "memory negative")
    quality = require_unit(add(positive, negative), "memory quality")
    direction = divide(subtract(positive, negative), quality) if quality > 0.0 else 0.0
    conflict = divide(multiply(2.0, min(positive, negative)), quality) if quality > 0.0 else 0.0
    evidence = require_signed_unit(subtract(positive, negative), "memory evidence")
    reliability = require_unit(abs(evidence), "memory reliability")
    uncertainty = require_unit(subtract(1.0, reliability), "memory uncertainty")
    return MvpMemoryMass(
        positive=positive,
        negative=negative,
        quality=quality,
        direction=require_signed_unit(direction, "memory direction"),
        conflict=require_unit(conflict, "memory conflict"),
        evidence=evidence,
        reliability=reliability,
        uncertainty=uncertainty,
        weights=weights,
    )


def fuse_b6(
    local: MvpB2Output,
    ordered_cases: Iterable[MvpAdvisoryPayload],
    *,
    memory_enabled: bool,
    empty_status: str = "EMPTY_IDENTITY",
) -> MvpB6Output:
    return fuse_b6_detailed(
        local,
        ordered_cases,
        memory_enabled=memory_enabled,
        empty_status=empty_status,
    ).output


def _audit(
    *,
    mode: str,
    memory_enabled: bool,
    local_values: tuple[float, float, float, float],
    cases: tuple[MvpAdvisoryPayload, ...],
    mass: MvpMemoryMass,
    gate: float,
    candidate: tuple[float, float, float, float],
    abstained: bool,
    output: MvpB6Output,
) -> MvpB6Audit:
    local_reliability, local_direction, local_evidence, local_uncertainty = local_values
    candidate_evidence, candidate_reliability, candidate_direction, candidate_uncertainty = candidate
    return MvpB6Audit(
        mode=mode,
        memory_enabled=memory_enabled,
        local_evidence=local_evidence,
        local_reliability=local_reliability,
        local_direction=local_direction,
        local_uncertainty=local_uncertainty,
        source_case_ids=tuple(case.case_id for case in cases),
        memory_positive=mass.positive,
        memory_negative=mass.negative,
        memory_quality=mass.quality,
        memory_direction=mass.direction,
        memory_conflict=mass.conflict,
        memory_evidence=mass.evidence,
        memory_reliability=mass.reliability,
        memory_uncertainty=mass.uncertainty,
        memory_weights=mass.weights,
        memory_gate=gate,
        candidate_evidence=candidate_evidence,
        candidate_reliability=candidate_reliability,
        candidate_direction=candidate_direction,
        candidate_uncertainty=candidate_uncertainty,
        abstained=abstained,
        output_evidence=output.e_commit,
        output_reliability=output.reliability_commit,
        output_direction=output.direction_commit,
        output_uncertainty=output.u_commit,
        output_status=output.memory_status,
    )


def fuse_b6_detailed(
    local: MvpB2Output,
    ordered_cases: Iterable[MvpAdvisoryPayload],
    *,
    memory_enabled: bool,
    empty_status: str = "EMPTY_IDENTITY",
) -> MvpB6DetailedResult:
    cases = tuple(ordered_cases)
    local_values = _local(local)
    zero_mass = MvpMemoryMass(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, ())
    if not memory_enabled:
        output = identity_b6(local, "DISABLED_IDENTITY")
        return MvpB6DetailedResult(
            output,
            _audit(
                mode="IDENTITY_DISABLED",
                memory_enabled=False,
                local_values=local_values,
                cases=(),
                mass=zero_mass,
                gate=0.0,
                candidate=(output.e_commit, output.reliability_commit, output.direction_commit, output.u_commit),
                abstained=False,
                output=output,
            ),
        )
    if not cases:
        output = identity_b6(local, empty_status)
        return MvpB6DetailedResult(
            output,
            _audit(
                mode="IDENTITY_EMPTY",
                memory_enabled=True,
                local_values=local_values,
                cases=(),
                mass=zero_mass,
                gate=0.0,
                candidate=(output.e_commit, output.reliability_commit, output.direction_commit, output.u_commit),
                abstained=False,
                output=output,
            ),
        )
    local_reliability, _local_direction, local_evidence, local_uncertainty = local_values
    mass = memory_mass(cases)
    gate = require_unit(multiply(local_uncertainty, mass.reliability), "memory gate")
    evidence_hat = add(
        multiply(subtract(1.0, gate), local_evidence),
        multiply(local_uncertainty, mass.evidence),
    )
    reliability_hat = add(
        multiply(subtract(1.0, gate), local_reliability),
        gate,
    )
    reliability_hat = require_unit(reliability_hat, "fused reliability")
    evidence_hat = require_signed_unit(evidence_hat, "fused evidence")
    if abs(evidence_hat) > reliability_hat + 1e-12:
        raise ValueError("fused evidence exceeds fused reliability")
    direction_hat = divide(evidence_hat, reliability_hat) if reliability_hat > 0.0 else 0.0
    direction_hat = require_signed_unit(direction_hat, "fused direction")
    uncertainty_hat = require_unit(subtract(1.0, abs(evidence_hat)), "fused uncertainty")
    internal_disagreement = strict_greater(mass.positive, 0.0) and strict_greater(mass.negative, 0.0)
    local_disagreement = compare(multiply(local_evidence, mass.evidence), 0.0) == -1
    uncertainty_not_improved = compare(uncertainty_hat, local_uncertainty) >= 0
    candidate = (evidence_hat, reliability_hat, direction_hat, uncertainty_hat)
    if strict_greater(mass.quality, 0.0) and (internal_disagreement or local_disagreement) and uncertainty_not_improved:
        output = identity_b6(local, "ABSTAIN_UNRESOLVED_CONFLICT")
        return MvpB6DetailedResult(
            output,
            _audit(
                mode="ABSTAIN",
                memory_enabled=True,
                local_values=local_values,
                cases=cases,
                mass=mass,
                gate=gate,
                candidate=candidate,
                abstained=True,
                output=output,
            ),
        )
    output = MvpB6Output(
        e_commit=evidence_hat,
        reliability_commit=reliability_hat,
        direction_commit=direction_hat,
        u_commit=uncertainty_hat,
        memory_status="FUSED",
        source_case_ids=tuple(case.case_id for case in cases),
    )
    return MvpB6DetailedResult(
        output,
        _audit(
            mode="FUSION",
            memory_enabled=True,
            local_values=local_values,
            cases=cases,
            mass=mass,
            gate=gate,
            candidate=candidate,
            abstained=False,
            output=output,
        ),
    )
