from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..codec import dumps, loads
from .diagnostics import build_evaluator_diagnostic_report
from .metrics import FRAME_TARGET_MANIFEST_TYPE, evaluate_binary_metrics, evaluate_frame_predictions
from .publisher import MvpEvaluatorPublisher
from .resolver import MvpEvaluatorResolver
from .targets import build_ucf_frame_target_manifest


def _jsonl(raw: bytes) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line:
            decoded = loads(line)
            if not isinstance(decoded, dict):
                raise ValueError("Evaluator prediction record is invalid")
            records.append(decoded)
    return tuple(records)


def evaluate_launch_plan(launch_plan_path: Path) -> dict[str, Any]:
    plan = loads(launch_plan_path.read_bytes())
    if not isinstance(plan, dict):
        raise ValueError("Evaluator launch plan is invalid")
    attempt_root = launch_plan_path.parents[2]
    allowed = tuple(
        (str(item["relative_ref"]), int(item["byte_length"]), str(item["sha256"]))
        for item in plan["allowed_inputs"]
    )
    resolver = MvpEvaluatorResolver(attempt_root, allowed)
    prediction_refs = tuple(str(value) for value in plan["readable_refs"])
    predictions = tuple(record for ref in prediction_refs for record in _jsonl(resolver.read(ref)))
    diagnostics: list[dict[str, Any]] = []
    for ref in plan["diagnostic_refs"]:
        value = loads(resolver.read(str(ref)))
        if not isinstance(value, dict):
            raise ValueError("Evaluator diagnostic record is invalid")
        diagnostics.append(value)
    target_manifest = loads(resolver.read(str(plan["annotation_manifest_ref"])))
    if not isinstance(target_manifest, dict):
        raise ValueError("Evaluator target manifest is invalid")
    ordered_predictions = tuple(sorted(predictions, key=lambda item: (str(item["video_id"]).encode(), int(item["window_ordinal"]))))
    if set(target_manifest) == {"records"}:
        target_by_key = {
            (str(record["video_id"]), str(record["window_id"])): int(record["target"])
            for record in target_manifest["records"]
        }
        labels = tuple(target_by_key[(str(item["video_id"]), str(item["window_id"]))] for item in ordered_predictions)
        scores = tuple(float(item["prediction"]) for item in ordered_predictions)
        metrics = {
            "metrics": evaluate_binary_metrics(labels, scores),
            "research_claim_status": str(plan["research_claim_status"]),
            "runtime_profile": str(plan["runtime_profile"]),
        }
    elif target_manifest.get("manifest_type") == FRAME_TARGET_MANIFEST_TYPE:
        frame_result = evaluate_frame_predictions(ordered_predictions, target_manifest)
        metrics = {
            "evaluation_level": "FRAME",
            **frame_result,
            "research_claim_status": str(plan["research_claim_status"]),
            "runtime_profile": str(plan["runtime_profile"]),
        }
    else:
        raise ValueError("Evaluator target manifest is invalid")
    publisher = MvpEvaluatorPublisher(
        launch_plan_path.parent,
        str(plan["metrics_ref"]),
        str(plan["diagnostic_report_ref"]),
        str(plan["receipt_ref"]),
    )
    diagnostic_report = build_evaluator_diagnostic_report(
        ordered_predictions,
        tuple(diagnostics),
        target_manifest,
    )
    diagnostic_receipt = publisher.publish_diagnostic_report(
        dumps(diagnostic_report),
        parent_payload_hashes=(
            str(plan["inference_freeze_hash"]),
            *(str(item["sha256"]) for item in plan["allowed_inputs"]),
        ),
    )
    metrics_receipt = publisher.publish_metrics(dumps(metrics))
    receipt_payload = {
        "diagnostic_report_hash": diagnostic_receipt.file_hash,
        "diagnostic_report_ref": diagnostic_receipt.relative_ref,
        "metrics_hash": metrics_receipt.file_hash,
        "metrics_ref": metrics_receipt.relative_ref,
        "research_claim_status": str(plan["research_claim_status"]),
        "runtime_profile": str(plan["runtime_profile"]),
        "status_code": "EVALUATION_COMPLETED",
    }
    receipt = publisher.publish_receipt(
        dumps(receipt_payload),
        parent_payload_hashes=(diagnostic_receipt.file_hash, metrics_receipt.file_hash),
    )
    return {
        "diagnostic_report_hash": diagnostic_receipt.file_hash,
        "diagnostic_report_ref": diagnostic_receipt.relative_ref,
        "metrics_hash": metrics_receipt.file_hash,
        "metrics_ref": metrics_receipt.relative_ref,
        "receipt_hash": receipt.file_hash,
        "receipt_ref": receipt.relative_ref,
        "status_code": "EVALUATION_COMPLETED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_mvp.evaluator.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--launch-plan", required=True)
    targets_parser = subparsers.add_parser("build-frame-targets")
    targets_parser.add_argument("--source-manifest", required=True)
    targets_parser.add_argument("--temporal-annotations", required=True)
    targets_parser.add_argument("--output", required=True)
    targets_parser.add_argument(
        "--experiment-config",
        choices=("O0", "O1", "I0", "I1", "I2", "I3", "I4", "C0", "C1", "S0"),
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "evaluate":
            result = evaluate_launch_plan(Path(args.launch_plan))
        else:
            receipt = build_ucf_frame_target_manifest(
                source_manifest_path=Path(args.source_manifest),
                temporal_annotation_path=Path(args.temporal_annotations),
                output_path=Path(args.output),
                experiment_config_id=str(args.experiment_config),
            )
            result = {
                "frame_count": receipt.frame_count,
                "output_path": str(receipt.output_path.resolve()),
                "output_sha256": receipt.output_sha256,
                "status_code": "FRAME_TARGETS_FROZEN",
                "video_count": receipt.video_count,
            }
    except Exception:
        status_code = "EVALUATOR_FAILED" if args.command == "evaluate" else "FRAME_TARGETS_FAILED"
        print(json.dumps({"status_code": status_code}, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
