from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from . import RESEARCH_CLAIM_STATUS, RUNTIME_PROFILE
from .adapters.real_assets import load_precomputed_input
from .artifacts.hashes import bytes_sha256, file_sha256
from .artifacts.publisher import MvpImmutablePublisher
from .artifacts.resolver import resolve_relative
from .codec import dumps, loads, payload_hash
from .contracts import MvpEvaluatorLaunchPlan
from .config import validate_inference_environment
from .failures import MvpFailure, fatal
from .ids import validate_attempt_id
from .memory.snapshot import read_snapshot
from .runtime.video_runner import compare_semantic_runs, run_precomputed_inference, run_synthetic_inference


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_fixture() -> Path:
    return _repo_root() / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"


def _attempt_root(project_root: Path, attempt_id: str) -> Path:
    return project_root / "data" / "agentic_outputs" / "mvp" / validate_attempt_id(attempt_id)


def _memory_root(project_root: Path, attempt_id: str) -> Path:
    return project_root / "data" / "agentic_memory" / "mvp" / validate_attempt_id(attempt_id)


def _decode_object(path: Path) -> dict[str, Any]:
    try:
        value = loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except Exception as exc:
        raise fatal("MVP_FREEZE_INVALID", "required freeze artifact is unreadable") from exc


def _hash_inventory(inference_root: Path, memory_root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for prefix, root in (("inference", inference_root), ("memory", memory_root)):
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().encode("utf-8")):
            inventory[f"{prefix}/{path.relative_to(root).as_posix()}"] = file_sha256(path)
    return inventory


def verify_frozen_attempt(project_root: Path, attempt_id: str, *, inference_quiescent: bool) -> dict[str, Any]:
    if not inference_quiescent:
        raise fatal("MVP_FREEZE_INVALID", "Evaluator requires inference-process quiescence")
    attempt_root = _attempt_root(project_root, attempt_id)
    inference_root = attempt_root / "inference"
    memory_root = _memory_root(project_root, attempt_id)
    output_path = inference_root / "freezes" / "mvp_output_hash_manifest.json"
    memory_freeze_path = inference_root / "freezes" / "mvp_memory_freeze.json"
    inference_freeze_path = inference_root / "freezes" / "mvp_inference_freeze.json"
    if not output_path.is_file() or not memory_freeze_path.is_file() or not inference_freeze_path.is_file():
        raise fatal("MVP_FREEZE_INVALID", "three-layer freeze is incomplete")
    output_manifest = _decode_object(output_path)
    semantic_output = {"entries": output_manifest.get("entries")}
    if output_manifest.get("payload_hash") != payload_hash(semantic_output) or output_manifest.get("attempt_id") != attempt_id:
        raise fatal("MVP_FREEZE_INVALID", "OutputHashManifest payload binding is invalid")
    entries = output_manifest.get("entries")
    if not isinstance(entries, list):
        raise fatal("MVP_FREEZE_INVALID", "OutputHashManifest entries are invalid")
    for entry in entries:
        relative = str(entry["relative_ref"])
        path = resolve_relative(inference_root, relative)
        try:
            if path.stat().st_size != int(entry["byte_length"]) or file_sha256(path) != str(entry["sha256"]):
                raise ValueError("entry mismatch")
        except Exception as exc:
            raise fatal("MVP_FREEZE_INVALID", "registered inference artifact changed") from exc

    memory_freeze = _decode_object(memory_freeze_path)
    snapshot = read_snapshot(memory_root)
    snapshot_path = memory_root / "memory_snapshot.json"
    if (
        memory_freeze.get("namespace_id") != attempt_id
        or memory_freeze.get("snapshot_payload_hash") != snapshot.get("payload_hash")
        or memory_freeze.get("snapshot_file_hash") != file_sha256(snapshot_path)
        or memory_freeze.get("version") != snapshot.get("version")
    ):
        raise fatal("MVP_FREEZE_INVALID", "MemoryFreeze does not bind the current snapshot")

    plan = _decode_object(inference_root / "mvp_inference_plan.json")
    video_order = plan.get("video_order")
    if (
        plan.get("attempt_id") != attempt_id
        or not isinstance(video_order, list)
        or not video_order
        or len(video_order) != len(set(str(value) for value in video_order))
    ):
        raise fatal("MVP_FREEZE_INVALID", "InferencePlan video set is invalid")
    prediction_entries = [entry for entry in entries if entry.get("artifact_type") == "prediction-freeze"]
    prediction_by_ref = {str(entry["relative_ref"]): entry for entry in prediction_entries}
    expected_prediction_refs = [f"freezes/prediction/{video_id}.json" for video_id in video_order]
    if set(prediction_by_ref) != set(expected_prediction_refs):
        raise fatal("MVP_FREEZE_INVALID", "planned video PredictionFreeze set is incomplete")
    prediction_hashes = [str(prediction_by_ref[relative]["sha256"]) for relative in expected_prediction_refs]
    inference_freeze = _decode_object(inference_freeze_path)
    if (
        inference_freeze.get("attempt_id") != attempt_id
        or inference_freeze.get("output_manifest_hash") != file_sha256(output_path)
        or inference_freeze.get("memory_freeze_hash") != file_sha256(memory_freeze_path)
        or inference_freeze.get("prediction_freeze_hashes") != prediction_hashes
    ):
        raise fatal("MVP_FREEZE_INVALID", "InferenceFreeze binding is invalid")
    return {
        "attempt_root": attempt_root,
        "hash_inventory": _hash_inventory(inference_root, memory_root),
        "inference_freeze_hash": file_sha256(inference_freeze_path),
        "inference_root": inference_root,
        "memory_root": memory_root,
        "output_manifest": output_manifest,
        "plan": plan,
    }


def _publish_synthetic_target_manifest(
    attempt_root: Path,
    evaluation_attempt_id: str,
    fixture_path: Path,
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_bytes())
    records = [
        {
            "target": 0 if str(video["video_id"]) == "mvp-video-a-reference" else 1,
            "video_id": str(video["video_id"]),
            "window_id": str(window["window_id"]),
        }
        for video in fixture["videos"]
        for window in video["windows"]
    ]
    target_payload = {"records": records}
    relative = f"evaluator_inputs/{evaluation_attempt_id}/targets.json"
    publisher = MvpImmutablePublisher(attempt_root, {"targets": relative})
    receipt = publisher.publish("targets", dumps(target_payload), payload_hash(target_payload))
    return {
        "byte_length": receipt.byte_length,
        "relative_ref": receipt.relative_ref,
        "sha256": receipt.file_hash,
    }


def _publish_external_target_manifest(
    verified: Mapping[str, Any],
    evaluation_attempt_id: str,
    target_manifest_path: Path,
) -> dict[str, Any]:
    try:
        target_payload = loads(target_manifest_path.read_bytes())
    except Exception as exc:
        raise fatal("MVP_FREEZE_INVALID", "Evaluator target manifest is unreadable") from exc
    if not isinstance(target_payload, dict) or set(target_payload) != {"records"}:
        raise fatal("MVP_FREEZE_INVALID", "Evaluator target manifest fields are invalid")
    records = target_payload["records"]
    if not isinstance(records, list) or not records:
        raise fatal("MVP_FREEZE_INVALID", "Evaluator target manifest is empty")
    target_keys: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"target", "video_id", "window_id"}:
            raise fatal("MVP_FREEZE_INVALID", "Evaluator target record fields are invalid")
        if record["target"] not in {0, 1}:
            raise fatal("MVP_FREEZE_INVALID", "Evaluator target is not binary")
        target_keys.append((str(record["video_id"]), str(record["window_id"])))
    if len(target_keys) != len(set(target_keys)):
        raise fatal("MVP_FREEZE_INVALID", "Evaluator target keys are duplicated")

    expected_keys: list[tuple[str, str]] = []
    prediction_entries = [
        entry for entry in verified["output_manifest"]["entries"] if entry.get("artifact_type") == "predictions"
    ]
    for entry in prediction_entries:
        raw = resolve_relative(verified["inference_root"], str(entry["relative_ref"])).read_bytes()
        for line in raw.splitlines():
            if line:
                prediction = loads(line)
                if not isinstance(prediction, dict):
                    raise fatal("MVP_FREEZE_INVALID", "frozen prediction record is invalid")
                expected_keys.append((str(prediction["video_id"]), str(prediction["window_id"])))
    if set(target_keys) != set(expected_keys) or len(target_keys) != len(expected_keys):
        raise fatal("MVP_FREEZE_INVALID", "Evaluator targets do not cover the frozen predictions exactly")
    ordered = sorted(records, key=lambda item: (str(item["video_id"]).encode("utf-8"), str(item["window_id"]).encode("utf-8")))
    canonical_payload = {"records": ordered}
    relative = f"evaluator_inputs/{evaluation_attempt_id}/targets.json"
    publisher = MvpImmutablePublisher(verified["attempt_root"], {"targets": relative})
    receipt = publisher.publish("targets", dumps(canonical_payload), payload_hash(canonical_payload))
    return {
        "byte_length": receipt.byte_length,
        "relative_ref": receipt.relative_ref,
        "sha256": receipt.file_hash,
    }


def _publish_launch_plan(
    verified: Mapping[str, Any],
    *,
    attempt_id: str,
    evaluation_attempt_id: str,
    target_entry: Mapping[str, Any],
) -> Path:
    prediction_entries = tuple(
        entry
        for entry in verified["output_manifest"]["entries"]
        if entry.get("artifact_type") == "predictions"
    )
    allowed_inputs = tuple(
        {
            "byte_length": int(entry["byte_length"]),
            "relative_ref": f"inference/{entry['relative_ref']}",
            "sha256": str(entry["sha256"]),
        }
        for entry in prediction_entries
    ) + (dict(target_entry),)
    plan = MvpEvaluatorLaunchPlan(
        attempt_id=attempt_id,
        evaluation_attempt_id=evaluation_attempt_id,
        inference_freeze_hash=str(verified["inference_freeze_hash"]),
        annotation_manifest_ref=str(target_entry["relative_ref"]),
        readable_refs=tuple(str(entry["relative_ref"]) for entry in allowed_inputs[:-1]),
        allowed_inputs=allowed_inputs,
        metrics_ref="metrics.json",
        receipt_ref="evaluation_receipt.json",
        runtime_profile=RUNTIME_PROFILE,
        research_claim_status=RESEARCH_CLAIM_STATUS,
    )
    evaluation_root = verified["attempt_root"] / "evaluation" / evaluation_attempt_id
    publisher = MvpImmutablePublisher(evaluation_root, {"launch": "mvp_evaluator_launch_plan.json"})
    publisher.publish("launch", dumps(asdict(plan)), payload_hash(asdict(plan)))
    return evaluation_root / "mvp_evaluator_launch_plan.json"


def _run_outer_attempt(
    *,
    attempt_id: str,
    project_root: Path,
    input_manifest_path: Path,
    input_kind: str,
    memory_enabled: bool,
    target_manifest_path: Path | None,
) -> dict[str, Any]:
    validate_inference_environment()
    validate_attempt_id(attempt_id)
    worker_command = [
        sys.executable,
        "-m",
        "src.research_mvp.launcher",
        "_inference-worker",
        "--attempt-id",
        attempt_id,
        "--project-root",
        str(project_root.resolve()),
        "--input-kind",
        input_kind,
        "--input-manifest",
        str(input_manifest_path.resolve()),
        "--memory-enabled",
        "1" if memory_enabled else "0",
    ]
    inference_process = subprocess.Popen(
        worker_command,
        cwd=_repo_root(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    inference_process_id = inference_process.pid
    inference_exit = inference_process.wait()
    if inference_exit != 0:
        raise fatal("MVP_FREEZE_INVALID", "inference process failed before a valid freeze")
    verified = verify_frozen_attempt(project_root, attempt_id, inference_quiescent=True)
    if input_kind == "precomputed":
        prepared, _bundle, _resolver = load_precomputed_input(input_manifest_path)
        if verified["plan"].get("asset_bundle_manifest_sha256") != prepared.get(
            "asset_bundle_manifest_sha256"
        ):
            raise fatal("MVP_FREEZE_INVALID", "inference plan does not bind the verified asset bundle")
    before_hashes = dict(verified["hash_inventory"])
    evaluation_attempt_id = f"{attempt_id}-evaluation"
    if target_manifest_path is None:
        if input_kind != "synthetic":
            raise fatal("MVP_FREEZE_INVALID", "real-asset evaluation requires an explicit target manifest")
        target_entry = _publish_synthetic_target_manifest(
            verified["attempt_root"], evaluation_attempt_id, input_manifest_path
        )
    else:
        target_entry = _publish_external_target_manifest(verified, evaluation_attempt_id, target_manifest_path)
    launch_plan_path = _publish_launch_plan(
        verified,
        attempt_id=attempt_id,
        evaluation_attempt_id=evaluation_attempt_id,
        target_entry=target_entry,
    )
    evaluator_process = subprocess.Popen(
        [sys.executable, "-m", "src.research_mvp.evaluator.cli", "evaluate", "--launch-plan", str(launch_plan_path.resolve())],
        cwd=_repo_root(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    evaluator_process_id = evaluator_process.pid
    stdout, _ = evaluator_process.communicate()
    evaluator_exit = evaluator_process.returncode
    if evaluator_exit != 0:
        raise fatal("EVALUATOR_BOUNDARY_VIOLATION", "Evaluator process failed safely")
    try:
        safe_result = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        raise fatal("EVALUATOR_BOUNDARY_VIOLATION", "Evaluator returned an invalid safe receipt") from exc
    after = verify_frozen_attempt(project_root, attempt_id, inference_quiescent=True)
    unchanged = before_hashes == after["hash_inventory"]
    if not unchanged:
        raise fatal("EVALUATOR_BOUNDARY_VIOLATION", "Evaluator changed inference or Memory facts")
    return {
        "attempt_id": attempt_id,
        "evaluator_process_exit_code": evaluator_exit,
        "evaluator_process_id": evaluator_process_id,
        "evaluator_started_after_inference_exit": True,
        "inference_memory_hashes_unchanged": True,
        "inference_process_exit_code": inference_exit,
        "inference_process_id": inference_process_id,
        "metrics_hash": safe_result["metrics_hash"],
        "metrics_ref": f"evaluation/{evaluation_attempt_id}/{safe_result['metrics_ref']}",
        "receipt_hash": safe_result["receipt_hash"],
        "receipt_ref": f"evaluation/{evaluation_attempt_id}/{safe_result['receipt_ref']}",
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "status_code": safe_result["status_code"],
    }


def run_outer_attempt(
    *,
    attempt_id: str,
    project_root: Path,
    fixture_path: Path,
    memory_enabled: bool,
) -> dict[str, Any]:
    return _run_outer_attempt(
        attempt_id=attempt_id,
        project_root=project_root,
        input_manifest_path=fixture_path,
        input_kind="synthetic",
        memory_enabled=memory_enabled,
        target_manifest_path=None,
    )


def run_asset_attempt(
    *,
    attempt_id: str,
    project_root: Path,
    input_manifest_path: Path,
    target_manifest_path: Path,
    memory_enabled: bool,
) -> dict[str, Any]:
    return _run_outer_attempt(
        attempt_id=attempt_id,
        project_root=project_root,
        input_manifest_path=input_manifest_path,
        input_kind="precomputed",
        memory_enabled=memory_enabled,
        target_manifest_path=target_manifest_path,
    )


def load_semantic_summary(project_root: Path, attempt_id: str) -> dict[str, Any]:
    verify_frozen_attempt(project_root, attempt_id, inference_quiescent=True)
    path = _attempt_root(project_root, attempt_id) / "inference" / "mvp_semantic_summary.json"
    return _decode_object(path)


def compare_frozen_attempts(project_root: Path, left_id: str, right_id: str) -> dict[str, Any]:
    left = load_semantic_summary(project_root, left_id)
    right = load_semantic_summary(project_root, right_id)
    comparison = {
        "comparison_id": f"{left_id}-vs-{right_id}",
        "left_attempt_id": left_id,
        **compare_semantic_runs(left, right),
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "right_attempt_id": right_id,
        "runtime_profile": RUNTIME_PROFILE,
    }
    root = project_root / "data" / "agentic_outputs" / "mvp" / "replay_comparisons" / comparison["comparison_id"]
    MvpImmutablePublisher(root, {"comparison": "comparison.json"}).publish(
        "comparison", dumps(comparison), payload_hash(comparison)
    )
    return comparison


def run_paired_smoke(project_root: Path, comparison_id: str, fixture_path: Path) -> dict[str, Any]:
    validate_attempt_id(comparison_id)
    enabled_id = f"{comparison_id}-enabled"
    disabled_id = f"{comparison_id}-disabled"
    enabled_receipt = run_outer_attempt(
        attempt_id=enabled_id,
        project_root=project_root,
        fixture_path=fixture_path,
        memory_enabled=True,
    )
    disabled_receipt = run_outer_attempt(
        attempt_id=disabled_id,
        project_root=project_root,
        fixture_path=fixture_path,
        memory_enabled=False,
    )
    enabled = load_semantic_summary(project_root, enabled_id)
    disabled = load_semantic_summary(project_root, disabled_id)
    comparison = {
        "comparison_id": comparison_id,
        "disabled_attempt_id": disabled_id,
        "disabled_metrics_ref": disabled_receipt["metrics_ref"],
        "enabled_attempt_id": enabled_id,
        "enabled_metrics_ref": enabled_receipt["metrics_ref"],
        "fixture_input_hash_equal": enabled["fixture_input_hash"] == disabled["fixture_input_hash"],
        "raw_b2_payload_hashes_equal": enabled["raw_b2_payload_hashes"] == disabled["raw_b2_payload_hashes"],
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "status_code": "PAIRED_SMOKE_COMPLETED",
    }
    root = project_root / "data" / "agentic_outputs" / "mvp" / "replay_comparisons" / comparison_id
    MvpImmutablePublisher(root, {"comparison": "comparison.json"}).publish(
        "comparison", dumps(comparison), payload_hash(comparison)
    )
    return comparison


def _inference_worker(args: argparse.Namespace) -> int:
    try:
        if args.input_kind == "synthetic":
            run_synthetic_inference(
                attempt_id=args.attempt_id,
                project_root=Path(args.project_root),
                fixture_path=Path(args.input_manifest),
                memory_enabled=args.memory_enabled == "1",
            )
        else:
            run_precomputed_inference(
                attempt_id=args.attempt_id,
                project_root=Path(args.project_root),
                input_manifest_path=Path(args.input_manifest),
                memory_enabled=args.memory_enabled == "1",
            )
    except Exception:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_mvp.launcher")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run-synthetic")
    run_parser.add_argument("--attempt-id", required=True)
    pair_parser = subparsers.add_parser("run-paired-smoke")
    pair_parser.add_argument("--comparison-id", required=True)
    asset_parser = subparsers.add_parser("run-asset-smoke")
    asset_parser.add_argument("--attempt-id", required=True)
    asset_parser.add_argument("--input-manifest", required=True)
    asset_parser.add_argument("--target-manifest", required=True)
    asset_parser.add_argument("--memory-enabled", choices=("0", "1"), default="1")
    worker_parser = subparsers.add_parser("_inference-worker")
    worker_parser.add_argument("--attempt-id", required=True)
    worker_parser.add_argument("--project-root", required=True)
    worker_parser.add_argument("--input-kind", choices=("synthetic", "precomputed"), required=True)
    worker_parser.add_argument("--input-manifest", required=True)
    worker_parser.add_argument("--memory-enabled", choices=("0", "1"), required=True)
    args = parser.parse_args(argv)
    if args.command == "_inference-worker":
        return _inference_worker(args)
    try:
        if args.command == "run-synthetic":
            result = run_outer_attempt(
                attempt_id=args.attempt_id,
                project_root=Path.cwd(),
                fixture_path=_default_fixture(),
                memory_enabled=True,
            )
        elif args.command == "run-paired-smoke":
            result = run_paired_smoke(Path.cwd(), args.comparison_id, _default_fixture())
        else:
            result = run_asset_attempt(
                attempt_id=args.attempt_id,
                project_root=Path.cwd(),
                input_manifest_path=Path(args.input_manifest),
                target_manifest_path=Path(args.target_manifest),
                memory_enabled=args.memory_enabled == "1",
            )
    except MvpFailure as exc:
        print(json.dumps({"failure_code": exc.code, "severity": exc.severity}, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
