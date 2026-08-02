from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Iterable

from ..contracts import MvpB2Output, MvpB4Commit, MvpB6Output, MvpInterval
from .numeric import (
    add,
    compare,
    divide,
    exp,
    median,
    multiply,
    numeric_equal,
    ordered_sum,
    require_signed_unit,
    require_unit,
    strict_greater,
    subtract,
)


EPS_CLOCK = 2.0**-52
ONE_BELOW_ONE = 1.0 - 2.0**-53


@dataclass(frozen=True, slots=True)
class MvpB4State:
    version: int
    fast: float
    slow: float
    state: str
    has_valid_observation: bool
    scene_age_us: float
    previous_coverages: tuple[tuple[str, tuple[MvpInterval, ...]], ...]
    completed_scene_durations_us: tuple[float, ...]

    @classmethod
    def initial(cls, *, state: str = "NORMAL") -> "MvpB4State":
        if state not in {"NORMAL", "SUSPICIOUS", "ABNORMAL", "RECOVERING"}:
            raise ValueError("invalid B4 state")
        return cls(0, 0.0, 0.0, state, False, 0.0, (), ())


@dataclass(frozen=True, slots=True)
class MvpB4Audit:
    previous_version: int
    previous_state: str
    previous_fast: float
    previous_slow: float
    previous_scene_age_us: float
    delta_us: int
    boundary: float
    effective_horizon_us: float
    scene_age_us: float
    scene_time_us: float
    tau_fast_us: float
    tau_slow_us: float
    alpha_fast: float
    alpha_slow: float
    rho_fast: float
    rho_slow: float
    valid_observation: bool
    input_evidence: float
    input_reliability: float
    input_direction: float
    slow_prior: float
    novelty: float
    momentum_weight: float
    fast: float
    slow: float
    momentum: float
    z: float
    input_uncertainty: float
    clock_gap: float
    gap_uncertainty: float
    uncertainty: float
    score_interval: tuple[float, float]
    new_state: str
    transition_reason: str


@dataclass(frozen=True, slots=True)
class MvpB4DetailedResult:
    commit: MvpB4Commit
    state: MvpB4State
    audit: MvpB4Audit


def _union(intervals: Iterable[MvpInterval]) -> tuple[MvpInterval, ...]:
    ordered = sorted(intervals, key=lambda item: (item.start_us, item.end_us))
    merged: list[MvpInterval] = []
    for interval in ordered:
        if not merged or interval.start_us > merged[-1].end_us:
            merged.append(interval)
        else:
            merged[-1] = MvpInterval(merged[-1].start_us, max(merged[-1].end_us, interval.end_us))
    return tuple(merged)


def _measure(intervals: Iterable[MvpInterval]) -> float:
    return ordered_sum(float(item.length_us) for item in _union(intervals))


def _overlap_ratio(current: tuple[MvpInterval, ...], previous: tuple[MvpInterval, ...]) -> float:
    current_union = _union(current)
    previous_union = _union(previous)
    denominator = _measure(current_union)
    if denominator == 0.0:
        return 0.0
    intersections: list[MvpInterval] = []
    for left in current_union:
        for right in previous_union:
            start = max(left.start_us, right.start_us)
            end = min(left.end_us, right.end_us)
            if end > start:
                intersections.append(MvpInterval(start, end))
    return require_unit(divide(_measure(intersections), denominator), "coverage overlap")


def _next_state(previous: str, confident_abnormal: bool, confident_normal: bool, positive_uncertain: bool) -> tuple[str, str]:
    if previous == "NORMAL":
        if confident_abnormal:
            return "ABNORMAL", "CONFIDENT_ABNORMAL"
        if positive_uncertain:
            return "SUSPICIOUS", "POSITIVE_UNCERTAIN"
        return "NORMAL", "HOLD_DEFAULT"
    if previous == "SUSPICIOUS":
        if confident_abnormal:
            return "ABNORMAL", "CONFIDENT_ABNORMAL"
        if confident_normal:
            return "NORMAL", "CONFIDENT_NORMAL"
        return "SUSPICIOUS", "HOLD_UNCERTAIN"
    if previous == "ABNORMAL":
        if confident_normal:
            return "RECOVERING", "CONFIDENT_NORMAL"
        return "ABNORMAL", "HOLD_UNCERTAIN"
    if previous == "RECOVERING":
        if confident_abnormal:
            return "ABNORMAL", "CONFIDENT_ABNORMAL"
        if confident_normal:
            return "NORMAL", "CONFIDENT_NORMAL"
        return "RECOVERING", "HOLD_UNCERTAIN"
    raise ValueError("invalid previous B4 state")


def compute_b4_detailed(
    video_id: str,
    window_id: str,
    window_ordinal: int,
    delta_us: int,
    final_b2: MvpB2Output,
    final_b6: MvpB6Output,
    previous: MvpB4State,
    *,
    boundary: float = 0.0,
) -> MvpB4DetailedResult:
    if isinstance(delta_us, bool) or not isinstance(delta_us, int) or delta_us <= 0 or delta_us > 2**63 - 1:
        raise ValueError("delta_us must be a positive int64")
    if previous.version != window_ordinal:
        raise ValueError("B4 state version does not match window ordinal")
    boundary = require_unit(boundary, "scene boundary")
    if not numeric_equal(final_b6.e_commit, multiply(final_b6.reliability_commit, final_b6.direction_commit)):
        raise ValueError("B6 evidence tuple is inconsistent")

    prior_coverages = dict(previous.previous_coverages)
    current_coverages: list[tuple[str, tuple[MvpInterval, ...]]] = []
    weighted_information: list[float] = []
    information_weights: list[float] = []
    for modality in sorted(final_b2.modalities, key=lambda item: item.channel.encode("utf-8")):
        coverage = _union(modality.observed_intervals)
        current_coverages.append((modality.channel, coverage))
        physical = _measure(coverage)
        overlap = _overlap_ratio(coverage, prior_coverages.get(modality.channel, ()))
        new_information = max(float(delta_us), multiply(physical, subtract(1.0, overlap)))
        weight = abs(subtract(modality.positive, modality.negative))
        information_weights.append(weight)
        weighted_information.append(multiply(weight, new_information))
    weight_sum = ordered_sum(information_weights)
    effective_horizon = float(delta_us) if weight_sum == 0.0 else divide(ordered_sum(weighted_information), add(weight_sum, EPS_CLOCK))
    tau_fast = max(float(delta_us), effective_horizon)
    scene_age = multiply(subtract(1.0, boundary), add(previous.scene_age_us, float(delta_us)))
    scene_basis = max(scene_age, effective_horizon)
    scene_time = median((*previous.completed_scene_durations_us, scene_basis))
    tau_slow = max(tau_fast, scene_time)
    alpha_fast = min(exp(-divide(float(delta_us), tau_fast)), ONE_BELOW_ONE)
    alpha_slow = min(exp(-divide(float(delta_us), tau_slow)), ONE_BELOW_ONE)
    rho_fast = require_unit(multiply(alpha_fast, subtract(1.0, boundary)), "fast retention")
    rho_slow = require_unit(multiply(alpha_slow, subtract(1.0, boundary)), "slow retention")
    if rho_fast > rho_slow + 1e-12 or rho_slow >= 1.0:
        raise ValueError("Elastic Dual Clock ordering invariant failed")

    reliability = require_unit(final_b6.reliability_commit, "B6 reliability")
    evidence = require_signed_unit(final_b6.e_commit, "B6 evidence")
    valid_observation = strict_greater(reliability, 0.0)
    if (not previous.has_valid_observation and valid_observation) or numeric_equal(boundary, 1.0):
        fast = evidence
        slow = evidence
    else:
        fast = add(multiply(rho_fast, previous.fast), multiply(subtract(1.0, rho_fast), evidence))
        slow = add(multiply(rho_slow, previous.slow), multiply(subtract(1.0, rho_slow), evidence))
    fast = require_signed_unit(fast, "fast belief")
    slow = require_signed_unit(slow, "slow belief")
    slow_prior = multiply(rho_slow, previous.slow)
    novelty = divide(abs(subtract(evidence, slow_prior)), 2.0)
    momentum_weight = require_unit(multiply(reliability, novelty), "momentum weight")
    momentum = add(multiply(momentum_weight, fast), multiply(subtract(1.0, momentum_weight), slow))
    momentum = require_signed_unit(momentum, "momentum")

    z = require_unit(divide(add(momentum, 1.0), 2.0), "B4 z")
    uncertainty_commit = require_unit(subtract(1.0, multiply(reliability, abs(final_b6.direction_commit))), "B4 input uncertainty")
    gap = divide(abs(subtract(fast, slow)), 2.0)
    gap_uncertain = multiply(subtract(1.0, reliability), gap)
    uncertainty = require_unit(subtract(1.0, multiply(subtract(1.0, uncertainty_commit), subtract(1.0, gap_uncertain))), "B4 uncertainty")
    lower = require_unit(max(0.0, min(1.0, subtract(z, divide(uncertainty, 2.0)))), "B4 lower")
    upper = require_unit(max(0.0, min(1.0, add(z, divide(uncertainty, 2.0)))), "B4 upper")
    confident_abnormal = compare(lower, 0.5) == 1
    confident_normal = compare(upper, 0.5) == -1
    positive_uncertain = compare(lower, 0.5) <= 0 and compare(upper, 0.5) >= 0 and compare(z, 0.5) == 1
    state, reason = _next_state(previous.state, confident_abnormal, confident_normal, positive_uncertain)

    commit = MvpB4Commit(
        video_id=video_id,
        window_id=window_id,
        window_ordinal=window_ordinal,
        version_before=previous.version,
        version_after=previous.version + 1,
        fast=fast,
        slow=slow,
        momentum=momentum,
        z=z,
        uncertainty=uncertainty,
        lower=lower,
        upper=upper,
        state=state,
        transition_reason=reason,
    )
    next_state = MvpB4State(
        version=previous.version + 1,
        fast=fast,
        slow=slow,
        state=state,
        has_valid_observation=previous.has_valid_observation or valid_observation,
        scene_age_us=scene_age,
        previous_coverages=tuple(current_coverages),
        completed_scene_durations_us=previous.completed_scene_durations_us,
    )
    audit = MvpB4Audit(
        previous_version=previous.version,
        previous_state=previous.state,
        previous_fast=previous.fast,
        previous_slow=previous.slow,
        previous_scene_age_us=previous.scene_age_us,
        delta_us=delta_us,
        boundary=boundary,
        effective_horizon_us=effective_horizon,
        scene_age_us=scene_age,
        scene_time_us=scene_time,
        tau_fast_us=tau_fast,
        tau_slow_us=tau_slow,
        alpha_fast=alpha_fast,
        alpha_slow=alpha_slow,
        rho_fast=rho_fast,
        rho_slow=rho_slow,
        valid_observation=valid_observation,
        input_evidence=evidence,
        input_reliability=reliability,
        input_direction=final_b6.direction_commit,
        slow_prior=slow_prior,
        novelty=novelty,
        momentum_weight=momentum_weight,
        fast=fast,
        slow=slow,
        momentum=momentum,
        z=z,
        input_uncertainty=uncertainty_commit,
        clock_gap=gap,
        gap_uncertainty=gap_uncertain,
        uncertainty=uncertainty,
        score_interval=(lower, upper),
        new_state=state,
        transition_reason=reason,
    )
    return MvpB4DetailedResult(commit, next_state, audit)


def compute_b4(
    video_id: str,
    window_id: str,
    window_ordinal: int,
    delta_us: int,
    final_b2: MvpB2Output,
    final_b6: MvpB6Output,
    previous: MvpB4State,
    *,
    boundary: float = 0.0,
) -> tuple[MvpB4Commit, MvpB4State]:
    result = compute_b4_detailed(
        video_id,
        window_id,
        window_ordinal,
        delta_us,
        final_b2,
        final_b6,
        previous,
        boundary=boundary,
    )
    return result.commit, result.state


class B4Committer:
    def __init__(self, initial_state: MvpB4State) -> None:
        self._state = initial_state
        self._committed: set[tuple[str, str]] = set()

    @property
    def state(self) -> MvpB4State:
        return self._state

    def commit(
        self,
        video_id: str,
        window_id: str,
        window_ordinal: int,
        delta_us: int,
        final_b2: MvpB2Output,
        final_b6: MvpB6Output,
        *,
        boundary: float = 0.0,
    ) -> MvpB4Commit:
        return self.commit_with_audit(
            video_id,
            window_id,
            window_ordinal,
            delta_us,
            final_b2,
            final_b6,
            boundary=boundary,
        ).commit

    def commit_with_audit(
        self,
        video_id: str,
        window_id: str,
        window_ordinal: int,
        delta_us: int,
        final_b2: MvpB2Output,
        final_b6: MvpB6Output,
        *,
        boundary: float = 0.0,
    ) -> MvpB4DetailedResult:
        key = (video_id, window_id)
        if key in self._committed:
            raise ValueError("B4 must commit exactly once per window")
        result = compute_b4_detailed(
            video_id,
            window_id,
            window_ordinal,
            delta_us,
            final_b2,
            final_b6,
            self._state,
            boundary=boundary,
        )
        self._committed.add(key)
        self._state = result.state
        return result
