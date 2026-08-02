from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from ..artifacts.publisher import MvpPublishReceipt
from ..codec import payload_hash
from ..contracts import MvpB2Output, MvpB4Commit, MvpB6Output, MvpWindowArtifact
from ..evidence.adapters import MvpAdapterResult
from ..evidence.b3_lite import MvpB3LiteResult
from ..math.b4 import MvpB4Audit
from ..math.b6 import MvpB6Audit
from ..math.numeric import numeric_equal


DIAGNOSTIC_SCHEMA_VERSION = "MVP_WINDOW_DIAGNOSTIC_V1"
_FORBIDDEN_KEYS = {"annotation", "ground_truth", "label", "metric_target", "target"}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_KEYS.intersection(str(key).casefold() for key in value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def assert_label_free_diagnostic(value: Mapping[str, Any]) -> None:
    if _contains_forbidden_key(value):
        raise ValueError("inference diagnostic contains evaluator-only fields")


def _informative(result: MvpAdapterResult) -> bool:
    if not result.accepted or result.observation is None:
        return False
    return not numeric_equal(result.observation.direction, 0.0) or any(
        atom.status == "VALID"
        and atom.role == "RISK"
        and atom.validity_gate == 1
        and not numeric_equal(atom.direction, 0.0)
        for atom in result.observation.atoms
    )


def _b2_summary(output: MvpB2Output) -> dict[str, Any]:
    return {
        "assessment_ids": list(output.assessment_ids),
        "conflict": output.conflict,
        "direction": output.direction,
        "e_local": output.e_local,
        "negative": output.negative,
        "payload_hash": payload_hash(asdict(output)),
        "positive": output.positive,
        "quality": output.quality,
        "slot": output.slot,
        "u_local": output.u_local,
    }


def _raw_evidence(
    window: Mapping[str, Any],
    base_result: MvpAdapterResult,
    b3: MvpB3LiteResult,
) -> tuple[dict[str, Any], ...]:
    artifact_refs = window.get("evidence_artifacts")
    refs = artifact_refs if isinstance(artifact_refs, Mapping) else {}
    trace_by_action = {trace.action: trace for trace in b3.tool_trace}
    records: list[dict[str, Any]] = []
    for action in ("VLM", *b3.attempted_actions):
        trace = trace_by_action.get(action)
        ref = refs.get(action)
        ref_mapping = ref if isinstance(ref, Mapping) else {}
        records.append(
            {
                "accepted": base_result.accepted if action == "VLM" else bool(trace and trace.accepted),
                "action": action,
                "payload_hash": base_result.raw_payload_hash if action == "VLM" else None if trace is None else trace.raw_payload_hash,
                "relative_ref": None if not ref_mapping else str(ref_mapping.get("relative_ref")),
            }
        )
    return tuple(records)


def build_window_diagnostic(
    *,
    window: Mapping[str, Any],
    base_result: MvpAdapterResult,
    b3: MvpB3LiteResult,
    b6: MvpB6Output,
    b6_audit: MvpB6Audit,
    b4: MvpB4Commit,
    b4_audit: MvpB4Audit,
    window_artifact: MvpWindowArtifact,
    window_receipt: MvpPublishReceipt,
    prediction_payload_hash: str,
) -> dict[str, Any]:
    raw_evidence = _raw_evidence(window, base_result, b3)
    base_b2 = b3.b2_outputs[0]
    diagnostic = {
        "b2": {
            "stages": [_b2_summary(output) for output in b3.b2_outputs],
            "tool_deltas": [
                {
                    "accepted": trace.accepted,
                    "action": trace.action,
                    "contributed": trace.contributed,
                    "delta": None if trace.b2_delta is None else asdict(trace.b2_delta),
                    "informative": trace.informative,
                }
                for trace in b3.tool_trace
            ],
        },
        "b3": {
            "accepted_actions": list(b3.accepted_actions),
            "attempted_actions": list(b3.attempted_actions),
            "eligibility": [asdict(audit) for audit in b3.eligibility_audits],
            "stop_reason": b3.stop_reason,
            "tool_actions": [asdict(trace) for trace in b3.tool_trace],
        },
        "b4": {
            "audit": asdict(b4_audit),
            "commit_payload_hash": payload_hash(asdict(b4)),
        },
        "b6": {
            "audit": asdict(b6_audit),
            "output_payload_hash": payload_hash(asdict(b6)),
        },
        "base_evidence": {
            "accepted": base_result.accepted,
            "contributed": any(
                not numeric_equal(value, 0.0)
                for value in (base_b2.positive, base_b2.negative, base_b2.quality, base_b2.e_local)
            ),
            "informative": _informative(base_result),
            "raw_payload_hash": base_result.raw_payload_hash,
        },
        "evidence_artifacts": list(raw_evidence),
        "lineage": {
            "b4_payload_hash": window_artifact.b4_payload_hash,
            "final_b2_payload_hash": window_artifact.final_b2_payload_hash,
            "final_b6_payload_hash": window_artifact.final_b6_payload_hash,
            "window_artifact_ref": window_receipt.relative_ref,
        },
        "prediction": {
            "payload_hash": prediction_payload_hash,
            "score": window_artifact.prediction,
        },
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "video_id": window_artifact.video_id,
        "window_id": window_artifact.window_id,
        "window_ordinal": window_artifact.window_ordinal,
    }
    assert_label_free_diagnostic(diagnostic)
    return diagnostic


def build_diagnostic_index_record(
    diagnostic: Mapping[str, Any],
    receipt: MvpPublishReceipt,
) -> dict[str, Any]:
    tool_actions = diagnostic["b3"]["tool_actions"]
    record = {
        "accepted_actions": [item["action"] for item in tool_actions if item["accepted"]],
        "contributed_actions": [item["action"] for item in tool_actions if item["contributed"]],
        "informative_actions": [item["action"] for item in tool_actions if item["informative"]],
        "prediction_score": diagnostic["prediction"]["score"],
        "relative_ref": receipt.relative_ref,
        "sha256": receipt.file_hash,
        "stop_reason": diagnostic["b3"]["stop_reason"],
        "video_id": diagnostic["video_id"],
        "window_id": diagnostic["window_id"],
        "window_ordinal": diagnostic["window_ordinal"],
    }
    assert_label_free_diagnostic(record)
    return record
