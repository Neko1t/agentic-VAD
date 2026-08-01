from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..codec import dumps, loads
from .metrics import evaluate_binary_metrics
from .publisher import MvpEvaluatorPublisher
from .resolver import MvpEvaluatorResolver


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
    target_manifest = loads(resolver.read(str(plan["annotation_manifest_ref"])))
    if not isinstance(target_manifest, dict) or set(target_manifest) != {"records"}:
        raise ValueError("Evaluator target manifest is invalid")
    target_by_key = {
        (str(record["video_id"]), str(record["window_id"])): int(record["target"])
        for record in target_manifest["records"]
    }
    ordered_predictions = tuple(sorted(predictions, key=lambda item: (str(item["video_id"]).encode(), int(item["window_ordinal"]))))
    labels = tuple(target_by_key[(str(item["video_id"]), str(item["window_id"]))] for item in ordered_predictions)
    scores = tuple(float(item["prediction"]) for item in ordered_predictions)
    metrics = {
        "metrics": evaluate_binary_metrics(labels, scores),
        "research_claim_status": str(plan["research_claim_status"]),
        "runtime_profile": str(plan["runtime_profile"]),
    }
    publisher = MvpEvaluatorPublisher(
        launch_plan_path.parent,
        str(plan["metrics_ref"]),
        str(plan["receipt_ref"]),
    )
    metrics_receipt = publisher.publish_metrics(dumps(metrics))
    receipt_payload = {
        "metrics_hash": metrics_receipt.file_hash,
        "metrics_ref": metrics_receipt.relative_ref,
        "research_claim_status": str(plan["research_claim_status"]),
        "runtime_profile": str(plan["runtime_profile"]),
        "status_code": "EVALUATION_COMPLETED",
    }
    receipt = publisher.publish_receipt(dumps(receipt_payload))
    return {
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
    args = parser.parse_args(argv)
    try:
        result = evaluate_launch_plan(Path(args.launch_plan))
    except Exception:
        print(json.dumps({"status_code": "EVALUATOR_FAILED"}, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
