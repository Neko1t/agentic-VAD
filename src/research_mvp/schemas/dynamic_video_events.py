from __future__ import annotations

import math
from typing import Any, Mapping


UNCERTAINTY_LEVELS = frozenset({"low", "medium", "high"})
EVENT_TYPES = frozenset(
    {
        "motion",
        "interaction",
        "impact",
        "fire_smoke",
        "crowd_response",
        "object_manipulation",
        "fall",
        "violence_like_motion",
        "stable_scene",
        "unknown",
    }
)
MOTION_PATTERNS = frozenset(
    {
        "approaching",
        "leaving",
        "running",
        "standing",
        "falling",
        "striking",
        "carrying",
        "manipulating",
        "burning",
        "gathering",
        "dispersing",
        "unknown",
    }
)
STATE_CHANGE_TYPES = frozenset(
    {"appears", "disappears", "starts", "stops", "intensifies", "spreads", "no_change", "unclear"}
)
VISIBILITY_LEVELS = frozenset({"clear", "partial", "occluded", "low_resolution", "dark", "camera_motion"})
TEMPORAL_RELATIONS = frozenset({"before", "overlaps", "causes_or_enables", "contrasts_with", "unknown"})


def clamp01(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(1.0, max(0.0, parsed))


def seconds(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def enum(value: Any, allowed: frozenset[str], default: str) -> str:
    parsed = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    return parsed if parsed in allowed else default


def text(value: Any) -> str:
    return str(value).strip()


def text_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [item for item in (text(item) for item in value) if item]
    parsed = text(value)
    return [parsed] if parsed else []


def normalize_dynamic_observation(
    raw: Mapping[str, Any],
    *,
    window_start_sec: float,
    window_end_sec: float,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if window_end_sec <= window_start_sec:
        raise ValueError("window time span must be non-empty")
    warnings: list[str] = []

    def clamp_time(value: Any, default: float, field: str) -> float:
        parsed = seconds(value, default)
        clamped = min(window_end_sec, max(window_start_sec, parsed))
        if clamped != parsed:
            warnings.append(f"{field}:CLAMPED_TO_EVIDENCE_CONTEXT")
        return clamped

    events: list[dict[str, Any]] = []
    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        warnings.append("events:REPLACED_NON_LIST")
        raw_events = []
    for index, event in enumerate(raw_events):
        if not isinstance(event, Mapping):
            warnings.append(f"events[{index}]:DROPPED_NON_OBJECT")
            continue
        start = clamp_time(event.get("start_sec"), window_start_sec, f"events[{index}].start_sec")
        end = clamp_time(event.get("end_sec"), window_end_sec, f"events[{index}].end_sec")
        if end < start:
            warnings.append(f"events[{index}]:REVERSED_TIME_REPAIRED")
            start, end = end, start
        uncertainty = enum(event.get("uncertainty"), UNCERTAINTY_LEVELS, "high")
        default_confidence = {"low": 0.75, "medium": 0.55, "high": 0.35}[uncertainty]
        events.append(
            {
                "action": text(event.get("action")) or "unknown",
                "confidence": clamp01(event.get("confidence"), default_confidence),
                "end_sec": end,
                "event_id": text(event.get("event_id")) or f"e{index + 1}",
                "event_type": enum(event.get("event_type"), EVENT_TYPES, "unknown"),
                "location": text(event.get("location")) or "unknown",
                "motion_pattern": enum(event.get("motion_pattern"), MOTION_PATTERNS, "unknown"),
                "normal_cues": text_list(event.get("normal_cues", [])),
                "object": text(event.get("object")) or "unknown",
                "risk_cues": text_list(event.get("risk_cues", [])),
                "start_sec": start,
                "state_change": text(event.get("state_change")),
                "state_change_type": enum(event.get("state_change_type"), STATE_CHANGE_TYPES, "unclear"),
                "subject": text(event.get("subject")) or "unknown",
                "uncertainty": uncertainty,
                "visibility": enum(event.get("visibility"), VISIBILITY_LEVELS, "partial"),
            }
        )
    if not events:
        warnings.append("events:INSERTED_STABLE_SCENE")
        events.append(
            {
                "action": "stable",
                "confidence": 0.35,
                "end_sec": window_end_sec,
                "event_id": "e1",
                "event_type": "stable_scene",
                "location": "unknown",
                "motion_pattern": "standing",
                "normal_cues": ["no salient dynamic change described"],
                "object": "unknown",
                "risk_cues": [],
                "start_sec": window_start_sec,
                "state_change": "no clear change described",
                "state_change_type": "no_change",
                "subject": "scene",
                "uncertainty": "high",
                "visibility": "partial",
            }
        )

    relations: list[dict[str, str]] = []
    raw_relations = raw.get("temporal_relations", [])
    if not isinstance(raw_relations, list):
        warnings.append("temporal_relations:REPLACED_NON_LIST")
        raw_relations = []
    for index, relation in enumerate(raw_relations):
        if not isinstance(relation, Mapping):
            warnings.append(f"temporal_relations[{index}]:DROPPED_NON_OBJECT")
            continue
        relations.append(
            {
                "explanation": text(relation.get("explanation")),
                "relation": enum(relation.get("relation"), TEMPORAL_RELATIONS, "unknown"),
                "source_event_id": text(relation.get("source_event_id")),
                "target_event_id": text(relation.get("target_event_id")),
            }
        )

    observation = {
        "events": events,
        "global_uncertainty": enum(raw.get("global_uncertainty"), UNCERTAINTY_LEVELS, "high"),
        "missing_evidence": text_list(raw.get("missing_evidence", [])),
        "parse_notes": text(raw.get("parse_notes")),
        "safety_relevant_observations": text_list(
            raw.get("safety_relevant_observations", raw.get("anomaly_relevant_observations", []))
        ),
        "summary": text(raw.get("summary")),
        "temporal_relations": relations,
        "window_end_sec": window_end_sec,
        "window_start_sec": window_start_sec,
    }
    return observation, tuple(warnings)
