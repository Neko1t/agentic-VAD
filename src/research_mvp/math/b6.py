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
    cases = tuple(ordered_cases)
    if not memory_enabled:
        return identity_b6(local, "DISABLED_IDENTITY")
    if not cases:
        return identity_b6(local, empty_status)
    local_reliability, _local_direction, local_evidence, local_uncertainty = _local(local)
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
    uncertainty_hat = require_unit(subtract(1.0, abs(evidence_hat)), "fused uncertainty")
    internal_disagreement = strict_greater(mass.positive, 0.0) and strict_greater(mass.negative, 0.0)
    local_disagreement = compare(multiply(local_evidence, mass.evidence), 0.0) == -1
    uncertainty_not_improved = compare(uncertainty_hat, local_uncertainty) >= 0
    if strict_greater(mass.quality, 0.0) and (internal_disagreement or local_disagreement) and uncertainty_not_improved:
        return identity_b6(local, "ABSTAIN_UNRESOLVED_CONFLICT")
    return MvpB6Output(
        e_commit=evidence_hat,
        reliability_commit=reliability_hat,
        direction_commit=require_signed_unit(direction_hat, "fused direction"),
        u_commit=uncertainty_hat,
        memory_status="FUSED",
        source_case_ids=tuple(case.case_id for case in cases),
    )
