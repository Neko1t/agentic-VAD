from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
import unicodedata

from ..contracts import (
    MvpB2Output,
    MvpEvidenceAtom,
    MvpFactContradiction,
    MvpInterval,
    MvpModalityEvidence,
    MvpPacketAssessment,
)
from .numeric import (
    add,
    divide,
    multiply,
    numeric_equal,
    ordered_product,
    ordered_sum,
    require_signed_unit,
    require_unit,
    subtract,
)


_SLOT = re.compile(r"^B2:(?:base|final|step-(?:000|001))$")
_FAMILIES = ("VISUAL", "AUDIO")
_ATOM_FAMILIES = (*_FAMILIES, "CONTEXT")
_ATOM_STATUSES = ("VALID", "EMPTY_VALID", "MISSING", "FAILED", "NOT_APPLICABLE")
_ATOM_ROLES = ("RISK", "CONTEXT", "BOUNDARY")
_QUALITY_POLICIES = ("MEASURED", "UNVERIFIED_CONTEXT_ONLY", "NOT_APPLICABLE")


def _clip(interval: MvpInterval, window: MvpInterval) -> MvpInterval | None:
    start = max(interval.start_us, window.start_us)
    end = min(interval.end_us, window.end_us)
    return None if end <= start else MvpInterval(start, end)


def _union(intervals: Iterable[MvpInterval]) -> tuple[MvpInterval, ...]:
    ordered = sorted(intervals, key=lambda item: (item.start_us, item.end_us))
    merged: list[MvpInterval] = []
    for interval in ordered:
        if not merged or interval.start_us > merged[-1].end_us:
            merged.append(interval)
        else:
            merged[-1] = MvpInterval(merged[-1].start_us, max(merged[-1].end_us, interval.end_us))
    return tuple(merged)


def _deduplicate(assessments: Iterable[MvpPacketAssessment]) -> tuple[MvpPacketAssessment, ...]:
    by_id: dict[str, MvpPacketAssessment] = {}
    for assessment in assessments:
        previous = by_id.get(assessment.assessment_id)
        if previous is not None and previous != assessment:
            raise ValueError("same assessment ID has different content")
        by_id[assessment.assessment_id] = assessment
    return tuple(by_id[key] for key in sorted(by_id, key=lambda value: value.encode("utf-8")))


def _normalize_fact_slot(slot: tuple[str, str, str, str] | None) -> tuple[str, str, str, str] | None:
    if slot is None:
        return None
    if len(slot) != 4:
        raise ValueError("fact slot must have entity/action/object/relation fields")
    normalized = tuple(unicodedata.normalize("NFKC", value).strip().casefold() for value in slot)
    if any(not value for value in normalized):
        raise ValueError("fact slot fields must be non-empty")
    return normalized  # type: ignore[return-value]


def _validate_atom(atom: MvpEvidenceAtom, target_window: MvpInterval) -> tuple[MvpInterval | None, float]:
    if not atom.atom_id:
        raise ValueError("atom ID must be non-empty")
    if atom.source_family not in _ATOM_FAMILIES:
        raise ValueError("atom source family is invalid")
    if atom.status not in _ATOM_STATUSES:
        raise ValueError("atom status is invalid")
    if atom.role not in _ATOM_ROLES:
        raise ValueError("atom role is invalid")
    direction = require_signed_unit(atom.direction, "atom direction")
    if atom.role == "CONTEXT" and direction != 0.0:
        raise ValueError("CONTEXT atom direction must be zero")
    if direction < 0.0 and not atom.interpretation_trace:
        raise ValueError("negative atom requires a frozen interpretation trace")
    if atom.validity_gate not in (0, 1):
        raise ValueError("atom validity gate must be zero or one")
    if atom.quality_policy not in _QUALITY_POLICIES:
        raise ValueError("atom quality policy is forbidden in RESEARCH_MVP")
    q_in = require_unit(atom.q_in, "atom q_in")
    q_src = require_unit(atom.q_src, "atom q_src")
    if atom.quality_policy == "UNVERIFIED_CONTEXT_ONLY":
        if atom.validity_gate != 0 or atom.role != "CONTEXT":
            raise ValueError("UNVERIFIED_CONTEXT_ONLY atom must be gated CONTEXT")
    if atom.quality_policy == "NOT_APPLICABLE" and atom.validity_gate != 0:
        raise ValueError("NOT_APPLICABLE atom must be gated")
    if atom.status in {"MISSING", "FAILED", "NOT_APPLICABLE"} and atom.validity_gate != 0:
        raise ValueError("unavailable atom status must be gated")
    _normalize_fact_slot(atom.fact_slot)
    overlap = _clip(atom.interval, target_window)
    reliability = multiply(float(atom.validity_gate), multiply(q_in, q_src))
    if atom.status != "VALID":
        reliability = 0.0
    return overlap, require_unit(reliability, "atom fact reliability")


def _validated_atoms(
    assessments: tuple[MvpPacketAssessment, ...],
    target_window: MvpInterval,
) -> tuple[
    dict[str, MvpEvidenceAtom],
    dict[str, MvpPacketAssessment],
    dict[str, MvpInterval | None],
    dict[str, float],
]:
    atoms: dict[str, MvpEvidenceAtom] = {}
    owners: dict[str, MvpPacketAssessment] = {}
    overlaps: dict[str, MvpInterval | None] = {}
    reliabilities: dict[str, float] = {}
    for assessment in assessments:
        for atom in sorted(assessment.atoms, key=lambda item: item.atom_id.encode("utf-8")):
            previous = atoms.get(atom.atom_id)
            if previous is not None and (previous != atom or owners[atom.atom_id].assessment_id != assessment.assessment_id):
                raise ValueError("same atom ID has different content or packet owner")
            if atom.source_family != assessment.family:
                raise ValueError("atom source family must match its packet assessment")
            overlap, reliability = _validate_atom(atom, target_window)
            atoms[atom.atom_id] = atom
            owners[atom.atom_id] = assessment
            overlaps[atom.atom_id] = overlap
            reliabilities[atom.atom_id] = reliability
    return atoms, owners, overlaps, reliabilities


def _temporal_overlap(left: MvpInterval, right: MvpInterval) -> float:
    intersection = max(0, min(left.end_us, right.end_us) - max(left.start_us, right.start_us))
    if intersection == 0:
        return 0.0
    return divide(float(intersection), float(min(left.length_us, right.length_us)))


def _residual_fact_conflict(
    contradictions: Iterable[MvpFactContradiction],
    atoms: dict[str, MvpEvidenceAtom],
    owners: dict[str, MvpPacketAssessment],
    overlaps: dict[str, MvpInterval | None],
    reliabilities: dict[str, float],
) -> tuple[float, tuple[tuple[str, str, float], ...]]:
    pair_scores: dict[tuple[str, str], float] = {}
    for contradiction in contradictions:
        if contradiction.left_atom_id == contradiction.right_atom_id:
            raise ValueError("fact contradiction must reference two atoms")
        pair = tuple(
            sorted(
                (contradiction.left_atom_id, contradiction.right_atom_id),
                key=lambda value: value.encode("utf-8"),
            )
        )
        score = require_unit(contradiction.score, "fact contradiction score")
        pair_scores[pair] = max(pair_scores.get(pair, 0.0), score)

    best = 0.0
    audit_pairs: list[tuple[str, str, float]] = []
    for left_id, right_id in sorted(
        pair_scores,
        key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8")),
    ):
        if left_id not in atoms or right_id not in atoms:
            raise ValueError("fact contradiction references an unknown atom")
        left = atoms[left_id]
        right = atoms[right_id]
        score = pair_scores[(left_id, right_id)]
        if score == 0.0 or left.status != "VALID" or right.status != "VALID":
            continue
        if left.source_family == right.source_family:
            continue
        left_interval = overlaps[left_id]
        right_interval = overlaps[right_id]
        if left_interval is None or right_interval is None:
            continue
        if _normalize_fact_slot(left.fact_slot) is None or _normalize_fact_slot(left.fact_slot) != _normalize_fact_slot(right.fact_slot):
            continue
        left_owner = owners[left_id]
        right_owner = owners[right_id]
        if left.direction * right.direction < 0.0 and left_owner.direction * right_owner.direction < 0.0:
            continue
        overlap = _temporal_overlap(left_interval, right_interval)
        strength = multiply(multiply(overlap, min(reliabilities[left_id], reliabilities[right_id])), score)
        if strength <= 0.0:
            continue
        strength = require_unit(strength, "fact contradiction strength")
        audit_pairs.append((left_id, right_id, strength))
        best = max(best, strength)
    return require_unit(best, "fact conflict"), tuple(audit_pairs)


def _contributing_atom_ids(
    window: MvpInterval,
    assessments: tuple[MvpPacketAssessment, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    supporting: set[str] = set()
    counter: set[str] = set()
    grouped: dict[str, list[MvpPacketAssessment]] = defaultdict(list)
    for assessment in assessments:
        grouped[assessment.channel].append(assessment)
    for channel in sorted(grouped, key=lambda value: value.encode("utf-8")):
        members = tuple(grouped[channel])
        clipped = {
            item.assessment_id: tuple(
                clip for clip in (_clip(interval, window) for interval in item.observed_intervals) if clip is not None
            )
            for item in members
        }
        endpoints = {window.start_us, window.end_us}
        for intervals in clipped.values():
            for interval in intervals:
                endpoints.update((interval.start_us, interval.end_us))
        points = sorted(endpoints)
        contributing_assessments: dict[str, int] = {}
        for start, end in zip(points, points[1:]):
            active = tuple(
                item
                for item in members
                if any(interval.start_us <= start and end <= interval.end_us for interval in clipped[item.assessment_id])
            )
            positive_values = {item.assessment_id: multiply(item.reliability, max(item.direction, 0.0)) for item in active}
            negative_values = {item.assessment_id: multiply(item.reliability, max(-item.direction, 0.0)) for item in active}
            positive_max = max(positive_values.values(), default=0.0)
            negative_max = max(negative_values.values(), default=0.0)
            for item in active:
                mask = 0
                if positive_max > 0.0 and positive_values[item.assessment_id] == positive_max:
                    mask |= 1
                if negative_max > 0.0 and negative_values[item.assessment_id] == negative_max:
                    mask |= 2
                contributing_assessments[item.assessment_id] = contributing_assessments.get(item.assessment_id, 0) | mask
        for item in members:
            mask = contributing_assessments.get(item.assessment_id, 0)
            valid_risk_ids = {
                atom.atom_id
                for atom in item.atoms
                if atom.status == "VALID" and atom.role == "RISK" and _clip(atom.interval, window) is not None
            }
            if mask & 1:
                supporting.update(valid_risk_ids)
            if mask & 2:
                counter.update(valid_risk_ids)
    order = lambda value: value.encode("utf-8")
    return tuple(sorted(supporting, key=order)), tuple(sorted(counter, key=order))


def _modality(
    window: MvpInterval,
    channel: str,
    assessments: tuple[MvpPacketAssessment, ...],
) -> MvpModalityEvidence:
    families = {assessment.family for assessment in assessments}
    if len(families) != 1 or next(iter(families)) not in _FAMILIES:
        raise ValueError("each channel must map to one frozen source family")
    family = next(iter(families))
    active_intervals: dict[str, tuple[MvpInterval, ...]] = {}
    endpoints = {window.start_us, window.end_us}
    original: list[MvpInterval] = []
    for assessment in assessments:
        reliability = require_unit(assessment.reliability, "assessment reliability")
        require_signed_unit(assessment.direction, "assessment direction")
        clips = tuple(item for item in (_clip(interval, window) for interval in assessment.observed_intervals) if item)
        active_intervals[assessment.assessment_id] = clips
        for interval in clips:
            endpoints.update((interval.start_us, interval.end_us))
        original.extend(assessment.observed_intervals)
        if reliability == 0.0:
            continue

    points = sorted(endpoints)
    positive_parts: list[float] = []
    negative_parts: list[float] = []
    window_length = float(window.length_us)
    for start, end in zip(points, points[1:]):
        if end <= start:
            continue
        active = [
            assessment
            for assessment in assessments
            if any(interval.start_us <= start and end <= interval.end_us for interval in active_intervals[assessment.assessment_id])
        ]
        positive = max(
            (multiply(assessment.reliability, max(assessment.direction, 0.0)) for assessment in active),
            default=0.0,
        )
        negative = max(
            (multiply(assessment.reliability, max(-assessment.direction, 0.0)) for assessment in active),
            default=0.0,
        )
        weight = divide(float(end - start), window_length)
        positive_parts.append(multiply(weight, positive))
        negative_parts.append(multiply(weight, negative))

    positive = require_unit(ordered_sum(positive_parts), "modality positive")
    negative = require_unit(ordered_sum(negative_parts), "modality negative")
    quality = require_unit(subtract(1.0, multiply(subtract(1.0, positive), subtract(1.0, negative))), "modality quality")
    direction = divide(subtract(positive, negative), quality) if quality > 0.0 else 0.0
    direction = require_signed_unit(direction, "modality direction")
    return MvpModalityEvidence(
        channel=channel,
        family=family,
        positive=positive,
        negative=negative,
        quality=quality,
        direction=direction,
        observed_intervals=_union(original),
    )


def build_b2_output(
    video_id: str,
    window_id: str,
    window_ordinal: int,
    window: MvpInterval,
    packet_assessments: Iterable[MvpPacketAssessment],
    *,
    slot: str,
    fact_contradictions: Iterable[MvpFactContradiction] = (),
    fact_tokens: Iterable[str] = (),
    embedding: Iterable[float] | None = None,
    temporal_triples: Iterable[tuple[str, str, str]] = (),
) -> MvpB2Output:
    if not _SLOT.fullmatch(slot):
        raise ValueError("B2 slot is outside the closed MVP grammar")
    assessments = _deduplicate(packet_assessments)
    atoms, atom_owners, atom_overlaps, atom_reliabilities = _validated_atoms(assessments, window)
    grouped: dict[str, list[MvpPacketAssessment]] = defaultdict(list)
    for assessment in assessments:
        grouped[assessment.channel].append(assessment)
    modalities = tuple(
        _modality(window, channel, tuple(grouped[channel]))
        for channel in sorted(grouped, key=lambda value: value.encode("utf-8"))
    )

    family_values: dict[str, tuple[float, float, float]] = {}
    for family in _FAMILIES:
        members = tuple(item for item in modalities if item.family == family)
        family_values[family] = (
            max((item.positive for item in members), default=0.0),
            max((item.negative for item in members), default=0.0),
            max((item.quality for item in members), default=0.0),
        )
    positive = require_unit(
        subtract(1.0, ordered_product(subtract(1.0, family_values[family][0]) for family in _FAMILIES)),
        "B2 positive",
    )
    negative = require_unit(
        subtract(1.0, ordered_product(subtract(1.0, family_values[family][1]) for family in _FAMILIES)),
        "B2 negative",
    )
    quality = require_unit(
        subtract(1.0, ordered_product(subtract(1.0, family_values[family][2]) for family in _FAMILIES)),
        "B2 quality",
    )
    dominant = max(positive, negative)
    direction = 0.0
    if quality > 0.0 and positive != negative:
        direction = divide(dominant if positive > negative else -dominant, quality)
    direction = require_signed_unit(direction, "B2 direction")
    direction_conflict = divide(min(positive, negative), dominant) if dominant > 0.0 else 0.0
    fact_conflict, fact_conflict_pairs = _residual_fact_conflict(
        fact_contradictions,
        atoms,
        atom_owners,
        atom_overlaps,
        atom_reliabilities,
    )
    conflict = require_unit(
        subtract(1.0, multiply(subtract(1.0, direction_conflict), subtract(1.0, fact_conflict))),
        "B2 conflict",
    )
    reliability = multiply(quality, subtract(1.0, conflict))
    evidence = require_signed_unit(multiply(reliability, direction), "B2 evidence")
    uncertainty = require_unit(subtract(1.0, abs(evidence)), "B2 uncertainty")
    expected = multiply(subtract(positive, negative), subtract(1.0, fact_conflict))
    if not numeric_equal(evidence, expected):
        raise ValueError("B2 evidence invariant failed")

    normalized_tokens = tuple(sorted(set(fact_tokens), key=lambda value: value.encode("utf-8")))
    normalized_triples = tuple(sorted(set(tuple(item) for item in temporal_triples)))
    normalized_embedding = None if embedding is None else tuple(float(value) for value in embedding)
    supporting_atom_ids, counter_atom_ids = _contributing_atom_ids(window, assessments)
    return MvpB2Output(
        video_id=video_id,
        window_id=window_id,
        window_ordinal=window_ordinal,
        slot=slot,
        positive=positive,
        negative=negative,
        quality=quality,
        direction=direction,
        direction_conflict=direction_conflict,
        fact_conflict=fact_conflict,
        conflict=conflict,
        e_local=evidence,
        u_local=uncertainty,
        modalities=modalities,
        assessment_ids=tuple(item.assessment_id for item in assessments),
        supporting_atom_ids=supporting_atom_ids,
        counter_atom_ids=counter_atom_ids,
        fact_conflict_pairs=fact_conflict_pairs,
        fact_tokens=normalized_tokens,
        embedding=normalized_embedding,
        temporal_triples=normalized_triples,
    )
