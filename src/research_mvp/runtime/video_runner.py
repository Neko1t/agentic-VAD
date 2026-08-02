from __future__ import annotations

import importlib.util
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .. import RESEARCH_CLAIM_STATUS, RUNTIME_PROFILE
from ..adapters.real_assets import MvpPrecomputedEvidenceResolver, load_precomputed_input
from ..adapters.semantic_scores import (
    MAPPING_IDENTITY,
    MvpSemanticScoreResolver,
    load_semantic_score_manifest,
)
from ..artifacts.hashes import bytes_sha256, file_sha256
from ..artifacts.publisher import MvpImmutablePublisher
from ..artifacts.resolver import validate_path_identity
from ..codec import dumps, payload_hash
from ..config import MvpInferenceConfig, validate_inference_boundary, validate_inference_environment
from ..contracts import MvpPredictionFreeze
from ..failures import MvpFailure, fatal
from ..ids import case_id
from ..math.b4 import B4Committer, MvpB4State
from ..memory.episode import EpisodeBuilder, MvpEpisodeWindow, summarize_episode
from ..memory.retrieval_key import build_retrieval_key
from ..memory.snapshot import MvpMemoryWriter, read_snapshot
from .inference_freeze import publish_inference_freeze, publish_memory_freeze, publish_output_manifest
from .diagnostics import build_diagnostic_index_record
from .window_runner import MvpWindowRun, _base_raw, case_capabilities, run_window


_REFERENCE_HASHES = {
    "docs/engineering_handoff/01_frozen_engineering_contracts.md": "016e2f195724c5416383d978dcf08e47340a0a61d904bcf9551db987158a1c2f",
    "docs/engineering_handoff/02_reference_algorithms.md": "8c50156640a0680474600d37a2fd378a14274b3fcb5b24b11dd6e172ca7c6b3c",
    "docs/implementation_design/02_runtime_agents_and_state_ownership_design.md": "ac1bc47d3f879aea80ce9195efd84285fa53961fa9ed452d6c36d0e6f1885df0",
    "docs/implementation_design/03_memory_persistence_retrieval_and_replay_design.md": "046625d5d868566c12de0d35952240a9314342141609ec1eaf5b69595b4bd221",
    "docs/implementation_design/04_migration_artifact_and_test_design.md": "902ad980a43f19b820ef34bc2ae2ed42e12b7503584c0555c584f548aa5be371",
    "docs/implementation_design/05_work_package_execution_plan.md": "514653478073f09aa943046d584df3b677a352677248a8acbd8e22eccaa70f4f",
}


def _planned_targets(fixture: Mapping[str, Any]) -> dict[str, str]:
    targets = {
        "plan": "mvp_inference_plan.json",
        "trace:window": "traces/window_trace.jsonl",
        "trace:tool": "traces/tool_trace.jsonl",
        "diagnostic-index": "diagnostics/window_diagnostics.jsonl",
        "summary": "mvp_semantic_summary.json",
        "freeze:output": "freezes/mvp_output_hash_manifest.json",
        "freeze:memory": "freezes/mvp_memory_freeze.json",
        "freeze:inference": "freezes/mvp_inference_freeze.json",
    }
    for video in fixture["videos"]:
        video_id = str(video["video_id"])
        targets[f"predictions:{video_id}"] = f"predictions/{video_id}.jsonl"
        targets[f"prediction-freeze:{video_id}"] = f"freezes/prediction/{video_id}.json"
        for window in video["windows"]:
            window_id = str(window["window_id"])
            targets[f"manifest:{video_id}:{window_id}"] = f"retrieval_manifests/{video_id}/{window_id}.json"
            targets[f"window:{video_id}:{window_id}"] = f"window_artifacts/{video_id}/{window_id}.json"
            targets[f"diagnostic-window:{video_id}:{window_id}"] = f"diagnostics/windows/{video_id}/{window_id}.json"
    return targets


def _source_manifest(repo_root: Path) -> tuple[dict[str, Any], ...]:
    source_root = repo_root / "src" / "research_mvp"
    return tuple(
        {
            "relative_ref": path.relative_to(repo_root).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in sorted(source_root.rglob("*.py"), key=lambda item: item.as_posix().encode("utf-8"))
    )


def _installed_package_file_hashes() -> tuple[dict[str, str], ...]:
    module_names = (
        "argparse",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "pathlib",
        "struct",
        "subprocess",
    )
    records: list[dict[str, str]] = []
    base = Path(sys.base_prefix).resolve()
    for module_name in module_names:
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            raise ValueError("frozen runtime module identity is unavailable")
        path = Path(spec.origin)
        if not path.is_file():
            if spec.origin == "built-in":
                records.append(
                    {
                        "module": module_name,
                        "relative_ref": "python-executable",
                        "sha256": file_sha256(Path(sys.executable)),
                    }
                )
                continue
            raise ValueError("frozen runtime module has no package file")
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(base).as_posix()
        except ValueError:
            relative = f"external/{module_name}/{resolved.name}"
        records.append(
            {
                "module": module_name,
                "relative_ref": relative,
                "sha256": file_sha256(resolved),
            }
        )
    return tuple(sorted(records, key=lambda item: item["module"].encode("utf-8")))


def _raw_output_manifest(fixture: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    bundle = fixture.get("asset_bundle_manifest")
    if isinstance(bundle, Mapping):
        records = (*bundle.get("raw_output_artifacts", ()), *bundle.get("evidence_artifacts", ()))
        return tuple(
            {
                "action": str(record["action"]),
                "artifact_id": str(record["artifact_id"]),
                "payload_hash": str(record["payload_hash"]),
                "relative_ref": str(record["relative_ref"]),
                "sha256": str(record["sha256"]),
            }
            for record in records
        )
    return tuple(
        {
            "artifact_id": f"base:{video['video_id']}:{window['window_id']}",
            "payload_hash": payload_hash(_base_raw(str(video["video_id"]), window)),
        }
        for video in fixture["videos"]
        for window in video["windows"]
    )


def _inference_plan(
    config: MvpInferenceConfig,
    fixture_path: Path,
    fixture: Mapping[str, Any],
    repo_root: Path,
    semantic_score_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    installed_files = _installed_package_file_hashes()
    raw_outputs = _raw_output_manifest(fixture)
    plan = {
        "adapter_identity": str(fixture.get("adapter_identity", "PRECOMPUTED_EVIDENCE_MVP_V0")),
        "asset_bundle_manifest_sha256": fixture.get("asset_bundle_manifest_sha256"),
        "attempt_id": config.attempt_id,
        "batch_size": config.batch_size,
        "device_policy": config.device_policy,
        "fixture_sha256": file_sha256(fixture_path),
        "initial_long_term_memory": "EMPTY",
        "memory_capacity": config.memory_capacity,
        "memory_namespace_id": config.memory_namespace_id,
        "model_sampling": {
            "deterministic_precomputed": True,
            "seed": 0,
            "temperature": 0.0,
            "top_p": 1.0,
        },
        "optional_pass_1": config.optional_pass_1,
        "python_executable": sys.executable,
        "python_executable_sha256": file_sha256(Path(sys.executable)),
        "python_runtime": platform.python_version(),
        "platform": platform.platform(),
        "installed_package_file_hashes": installed_files,
        "reference_document_hashes": _REFERENCE_HASHES,
        "reservoir_seed": 0,
        "resume": config.resume,
        "retrieval_k": config.retrieval_k,
        "rrf_constant": config.rrf_constant,
        "runtime_profile": config.runtime_profile,
        "raw_output_artifacts": raw_outputs,
        "source_file_manifest": _source_manifest(repo_root),
        "tool_action_order": list(config.tool_action_order),
        "tool_policy": config.tool_policy,
        "video_order": [str(video["video_id"]) for video in fixture["videos"]],
        "video_workers": config.video_workers,
        "window_workers": config.window_workers,
    }
    bundle = fixture.get("asset_bundle_manifest")
    if isinstance(bundle, Mapping):
        plan["precompute_provenance"] = {
            "backend_identity": str(bundle["backend_identity"]),
            "model_config": dict(bundle["model_config"]),
            "model_files": list(bundle["model_files"]),
            "model_identity_payload_hash": str(bundle["model_identity_payload_hash"]),
            "smoke_mapper_identity": str(bundle["smoke_mapper_identity"]),
            "source_assets": list(bundle["source_assets"]),
            "source_manifest_sha256": str(bundle["source_manifest_sha256"]),
        }
    if fixture.get("manifest_type") == "MVP_PRECOMPUTED_INPUT_V1":
        plan["dataset_id"] = str(fixture["dataset_id"])
        plan["decision_point_count"] = int(fixture["decision_point_count"])
        plan["frame_interval"] = int(fixture["decision_stride_frames"])
        plan["frame_rate"] = dict(fixture["frame_rate"])
        plan["temporal_protocol"] = str(fixture["temporal_protocol"])
    if semantic_score_manifest_sha256 is None:
        plan["base_evidence_mapper_identity"] = str(
            plan.get("precompute_provenance", {}).get("smoke_mapper_identity", "SYNTHETIC_BASE_EVIDENCE_V0")
        )
    else:
        plan["base_evidence_mapper_identity"] = MAPPING_IDENTITY
        plan["semantic_mapping_identity"] = MAPPING_IDENTITY
        plan["semantic_score_manifest_sha256"] = semantic_score_manifest_sha256
    return plan


def _prediction_freeze(video_id: str, runs: tuple[MvpWindowRun, ...]) -> MvpPredictionFreeze:
    semantic = {
        "ordered_prediction_payload_hashes": [run.prediction_payload_hash for run in runs],
        "ordered_window_artifact_hashes": [run.window_receipt.file_hash for run in runs],
        "video_id": video_id,
    }
    return MvpPredictionFreeze(
        video_id=video_id,
        ordered_window_artifact_hashes=tuple(semantic["ordered_window_artifact_hashes"]),
        ordered_prediction_payload_hashes=tuple(semantic["ordered_prediction_payload_hashes"]),
        payload_hash=payload_hash(semantic),
    )


def _episode_candidate(
    *,
    video_id: str,
    episode: Any,
    runs: tuple[MvpWindowRun, ...],
    prediction_freeze_hash: str | None,
    scope: str = "LONG_TERM",
) -> dict[str, Any] | None:
    by_ordinal = {run.window_artifact.window_ordinal: run for run in runs}
    selected = tuple(by_ordinal[ordinal] for ordinal in episode.member_window_ordinals)
    if not selected or not any(run.final_b2.assessment_ids for run in selected):
        return None
    summary = summarize_episode(
        episode,
        tuple(
            MvpEpisodeWindow(
                window_ordinal=run.window_artifact.window_ordinal,
                window_id=run.window_artifact.window_id,
                delta_us=run.delta_us,
                final_b2=run.final_b2,
            )
            for run in selected
        ),
    )
    if summary.reliability <= 0.0:
        return None
    role = episode.role.casefold()
    if scope == "LONG_TERM":
        if prediction_freeze_hash is None or len(prediction_freeze_hash) != 64:
            raise ValueError("Long-Term case requires PredictionFreeze")
        candidate_case_id = case_id(video_id, role, episode.ordinal)
    elif scope == "SESSION":
        if prediction_freeze_hash is not None:
            raise ValueError("Session case must not bind PredictionFreeze")
        suffix = video_id.removeprefix("mvp-video-")
        candidate_case_id = f"mvp-session-case-{suffix}-{role}-{episode.ordinal:04d}"
    else:
        raise ValueError("case scope is outside the MVP registry")
    advisory = {
        "C": summary.consistency,
        "R": summary.reliability,
        "atom_ids": list(summary.atom_ids),
        "d": summary.direction,
    }
    advisory_hash = payload_hash(advisory)
    retrieval_key = build_retrieval_key(
        case_id=candidate_case_id,
        source_video_id=video_id,
        scope=scope,
        payload_hash_value=advisory_hash,
        embedding=summary.embedding,
        tokens=summary.tokens,
        temporal_triples=summary.temporal_triples,
        visible_from_window_ordinal=episode.visible_from_window_ordinal if scope == "SESSION" else None,
    )
    return {
        "advisory_payload": advisory,
        "case_id": candidate_case_id,
        "derivation": "LOCAL_FINAL_B2_ONLY",
        "local_final_b2_parent_hashes": [payload_hash(asdict(run.final_b2)) for run in selected],
        "retrieval_key": {
            "embedding": None if retrieval_key.embedding is None else list(retrieval_key.embedding),
            "key_hash": retrieval_key.key_hash,
            "payload_hash": retrieval_key.payload_hash,
            "temporal_triples": [list(item) for item in retrieval_key.temporal_triples],
            "tokens": list(retrieval_key.tokens),
            "visible_from_window_ordinal": retrieval_key.visible_from_window_ordinal,
        },
        "scope": scope,
        "source_prediction_freeze_hash": prediction_freeze_hash,
        "source_video_id": video_id,
    }


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return b"".join(dumps(record) + b"\n" for record in records)


def run_synthetic_inference(
    *,
    attempt_id: str,
    project_root: Path,
    fixture_path: Path,
    memory_enabled: bool,
    memory_fault_video_id: str | None = None,
    memory_read_fault_at: tuple[str, int] | None = None,
) -> dict[str, Any]:
    validate_inference_environment()
    fixture = json.loads(fixture_path.read_bytes())
    validate_inference_boundary(fixture)
    return _run_inference(
        attempt_id=attempt_id,
        project_root=project_root,
        input_manifest_path=fixture_path,
        fixture=fixture,
        memory_enabled=memory_enabled,
        memory_fault_video_id=memory_fault_video_id,
        memory_read_fault_at=memory_read_fault_at,
    )


def run_precomputed_inference(
    *,
    attempt_id: str,
    project_root: Path,
    input_manifest_path: Path,
    memory_enabled: bool,
    tool_policy: str = "ALL",
    semantic_score_manifest_path: Path | None = None,
    semantic_score_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    validate_inference_environment()
    fixture, _bundle, evidence_resolver = load_precomputed_input(input_manifest_path)
    if (semantic_score_manifest_path is None) != (semantic_score_manifest_sha256 is None):
        raise fatal("MVP_FREEZE_INVALID", "semantic score path and hash must be supplied together")
    semantic_score_resolver = (
        None
        if semantic_score_manifest_path is None
        else load_semantic_score_manifest(
            semantic_score_manifest_path,
            expected_sha256=str(semantic_score_manifest_sha256),
            input_manifest_path=input_manifest_path,
        )
    )
    validate_inference_boundary(fixture)
    return _run_inference(
        attempt_id=attempt_id,
        project_root=project_root,
        input_manifest_path=input_manifest_path,
        fixture=fixture,
        memory_enabled=memory_enabled,
        evidence_resolver=evidence_resolver,
        tool_policy=tool_policy,
        semantic_score_resolver=semantic_score_resolver,
        semantic_score_manifest_sha256=semantic_score_manifest_sha256,
    )


def _run_inference(
    *,
    attempt_id: str,
    project_root: Path,
    input_manifest_path: Path,
    fixture: Mapping[str, Any],
    memory_enabled: bool,
    memory_fault_video_id: str | None = None,
    memory_read_fault_at: tuple[str, int] | None = None,
    evidence_resolver: MvpPrecomputedEvidenceResolver | None = None,
    tool_policy: str = "ALL",
    semantic_score_resolver: MvpSemanticScoreResolver | None = None,
    semantic_score_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    config = MvpInferenceConfig.reference(attempt_id, project_root, tool_policy=tool_policy)
    output_attempt_root = config.output_root
    validate_path_identity(output_attempt_root)
    validate_path_identity(config.memory_root)
    if output_attempt_root.exists() or output_attempt_root.is_symlink():
        raise ValueError("reference output attempt must be fresh")
    writer = MvpMemoryWriter.create_fresh(config.memory_root, config.memory_namespace_id)
    last_verified_snapshot = read_snapshot(config.memory_root)
    publisher = MvpImmutablePublisher(output_attempt_root / "inference", _planned_targets(fixture))
    plan = _inference_plan(
        config,
        input_manifest_path,
        fixture,
        repo_root,
        semantic_score_manifest_sha256=semantic_score_manifest_sha256,
    )
    plan_parent_list = [
        str(plan["fixture_sha256"]),
        str(plan["python_executable_sha256"]),
        *(str(item["sha256"]) for item in plan["source_file_manifest"]),
        *(str(value) for value in plan["reference_document_hashes"].values()),
        *(str(item["sha256"]) for item in plan["installed_package_file_hashes"]),
        *(str(item["payload_hash"]) for item in plan["raw_output_artifacts"]),
    ]
    if plan.get("asset_bundle_manifest_sha256") is not None:
        plan_parent_list.append(str(plan["asset_bundle_manifest_sha256"]))
        provenance = plan["precompute_provenance"]
        plan_parent_list.extend(str(item["sha256"]) for item in provenance["model_files"])
        plan_parent_list.extend(str(item["sha256"]) for item in provenance["source_assets"])
        plan_parent_list.append(str(provenance["model_identity_payload_hash"]))
    if semantic_score_manifest_sha256 is not None:
        plan_parent_list.append(semantic_score_manifest_sha256)
    plan_parents = tuple(plan_parent_list)
    plan_semantic = {key: value for key, value in plan.items() if key not in {"attempt_id", "memory_namespace_id"}}
    publisher.publish(
        "plan",
        dumps(plan),
        payload_hash(plan),
        parent_payload_hashes=plan_parents,
        semantic_payload_hash=payload_hash(plan_semantic),
    )

    all_window_runs: list[MvpWindowRun] = []
    video_summaries: list[dict[str, Any]] = []
    prediction_freeze_hashes: list[str] = []
    for expected_video_ordinal, video in enumerate(fixture["videos"]):
        video_id = str(video["video_id"])
        commit_count_at_video_start = writer.commit_count
        episode_builder = EpisodeBuilder(video_id)
        b4_committer = B4Committer(MvpB4State.initial())
        window_runs: list[MvpWindowRun] = []
        session_keys: list[Any] = []
        session_payloads: dict[str, Mapping[str, Any]] = {}
        for expected_window_ordinal, window in enumerate(video["windows"]):
            if window["ordinal"] != expected_window_ordinal:
                raise ValueError("MVP window order violation")
            memory_unavailable: MvpFailure | None = None
            try:
                if memory_read_fault_at == (video_id, expected_window_ordinal):
                    raise fatal("MVP_MEMORY_UNAVAILABLE", "snapshot read or hash verification failed")
                snapshot = read_snapshot(config.memory_root)
                last_verified_snapshot = snapshot
            except MvpFailure as exc:
                if exc.code != "MVP_MEMORY_UNAVAILABLE":
                    raise
                snapshot = last_verified_snapshot
                memory_unavailable = exc
            run = run_window(
                video_id=video_id,
                window=window,
                snapshot=snapshot,
                publisher=publisher,
                b4_committer=b4_committer,
                episode_builder=episode_builder,
                memory_enabled=memory_enabled,
                session_keys=tuple(session_keys),
                session_payloads=session_payloads,
                memory_status_override="MVP_MEMORY_UNAVAILABLE" if memory_unavailable is not None else None,
                evidence_loader=None
                if evidence_resolver is None
                else lambda action, _video_id=video_id, _window=window: evidence_resolver.load(
                    _video_id, _window, action
                ),
                semantic_evidence_mapper=None
                if semantic_score_resolver is None
                else semantic_score_resolver.map_evidence,
                semantic_score_manifest_sha256=semantic_score_manifest_sha256,
                tool_action_order=config.tool_action_order,
            )
            window_runs.append(run)
            all_window_runs.append(run)
            if memory_unavailable is not None:
                sealed_predictions = [
                    {
                        **item.prediction_record,
                        "prediction_payload_hash": item.prediction_payload_hash,
                    }
                    for item in window_runs
                ]
                sealed_bytes = _jsonl(sealed_predictions)
                publisher.publish(
                    f"predictions:{video_id}",
                    sealed_bytes,
                    bytes_sha256(sealed_bytes),
                    parent_payload_hashes=tuple(item.prediction_payload_hash for item in window_runs),
                )
                raise memory_unavailable
            published_session_ids: list[str] = []
            for closed_episode in run.closed_episodes if memory_enabled else ():
                session_case = _episode_candidate(
                    video_id=video_id,
                    episode=closed_episode,
                    runs=tuple(window_runs),
                    prediction_freeze_hash=None,
                    scope="SESSION",
                )
                if session_case is None:
                    continue
                session_key, session_payload = case_capabilities(session_case)
                session_keys.append(session_key)
                session_payloads[session_key.case_id] = session_payload
                published_session_ids.append(session_key.case_id)
            run.trace["closed_episode_ids"] = [episode.episode_id for episode in run.closed_episodes]
            run.trace["published_session_case_ids"] = published_session_ids
            if published_session_ids:
                run.trace["causal_chain"].append("SESSION_PUBLISHED")

        episodes = episode_builder.close_video()
        runs_tuple = tuple(window_runs)
        predictions = [
            {
                **run.prediction_record,
                "prediction_payload_hash": run.prediction_payload_hash,
            }
            for run in runs_tuple
        ]
        prediction_bytes = _jsonl(predictions)
        publisher.publish(
            f"predictions:{video_id}",
            prediction_bytes,
            bytes_sha256(prediction_bytes),
            parent_payload_hashes=tuple(run.prediction_payload_hash for run in runs_tuple),
        )
        commit_count_before = writer.commit_count
        prediction_freeze = _prediction_freeze(video_id, runs_tuple)
        prediction_freeze_receipt = publisher.publish(
            f"prediction-freeze:{video_id}",
            dumps(asdict(prediction_freeze)),
            payload_hash(asdict(prediction_freeze)),
            parent_payload_hashes=(
                *prediction_freeze.ordered_window_artifact_hashes,
                *prediction_freeze.ordered_prediction_payload_hashes,
            ),
            semantic_payload_hash=prediction_freeze.payload_hash,
        )
        prediction_freeze_hashes.append(prediction_freeze_receipt.file_hash)
        candidates = (
            tuple(
                candidate
                for episode in episodes
                if (candidate := _episode_candidate(
                    video_id=video_id,
                    episode=episode,
                    runs=runs_tuple,
                    prediction_freeze_hash=prediction_freeze_receipt.file_hash,
                    scope="LONG_TERM",
                ))
                is not None
            )
            if memory_enabled
            else ()
        )
        def memory_fault(stage: str) -> None:
            if video_id == memory_fault_video_id and stage == "before_replace":
                raise OSError("injected video-level Memory commit failure")

        if memory_enabled:
            last_verified_snapshot = writer.commit_video(
                video_id=video_id,
                prediction_freeze_hash=prediction_freeze_receipt.file_hash,
                prediction_freeze_accepted=prediction_freeze_receipt.accepted,
                candidates=candidates,
                fault_injector=memory_fault if memory_fault_video_id is not None else None,
            )
        video_summaries.append(
            {
                "memory_commit_count_after_prediction_freeze": writer.commit_count,
                "memory_commit_count_at_video_start": commit_count_at_video_start,
                "memory_commit_count_before_prediction_freeze": commit_count_before,
                "prediction_freeze_hash": prediction_freeze_receipt.file_hash,
                "prediction_payload_hashes": [run.prediction_payload_hash for run in runs_tuple],
                "retrieval_orders": [list(run.retrieval_order) for run in runs_tuple],
                "session_case_count": len(session_keys),
                "session_case_ids": [key.case_id for key in session_keys],
                "video_id": video_id,
                "view_orders": [
                    {name: list(order) for name, order in run.view_orders}
                    for run in runs_tuple
                ],
            }
        )

    window_trace_records = [run.trace for run in all_window_runs]
    tool_trace_records = [
        {
            "accepted": trace.accepted,
            "action": trace.action,
            "b2_delta": None if trace.b2_delta is None else asdict(trace.b2_delta),
            "contributed": trace.contributed,
            "failure_code": trace.failure_code,
            "informative": trace.informative,
            "raw_payload_hash": trace.raw_payload_hash,
            "status": trace.status,
            "eligibility_reasons": list(trace.eligibility_reasons),
            "video_id": run.window_artifact.video_id,
            "window_id": run.window_artifact.window_id,
        }
        for run in all_window_runs
        for trace in run.b3.tool_trace
    ]
    window_trace_bytes = _jsonl(window_trace_records)
    tool_trace_bytes = _jsonl(tool_trace_records)
    publisher.publish(
        "trace:window",
        window_trace_bytes,
        bytes_sha256(window_trace_bytes),
        parent_payload_hashes=tuple(run.window_receipt.payload_hash for run in all_window_runs),
    )
    tool_parents = tuple(
        trace.raw_payload_hash
        for run in all_window_runs
        for trace in run.b3.tool_trace
        if trace.raw_payload_hash is not None
    )
    publisher.publish(
        "trace:tool",
        tool_trace_bytes,
        bytes_sha256(tool_trace_bytes),
        parent_payload_hashes=tool_parents or (str(plan["fixture_sha256"]),),
    )
    diagnostic_index_records = [
        build_diagnostic_index_record(run.diagnostic, run.diagnostic_receipt)
        for run in all_window_runs
    ]
    diagnostic_index_bytes = _jsonl(diagnostic_index_records)
    diagnostic_index_receipt = publisher.publish(
        "diagnostic-index",
        diagnostic_index_bytes,
        bytes_sha256(diagnostic_index_bytes),
        parent_payload_hashes=tuple(run.diagnostic_receipt.file_hash for run in all_window_runs),
    )
    final_snapshot = read_snapshot(config.memory_root)
    semantic_cases = [
        {key: value for key, value in case.items() if key != "source_prediction_freeze_hash"}
        for case in final_snapshot["cases"]
    ]
    memory_semantic_hash = payload_hash({"cases": semantic_cases})
    semantic_summary = {
        "fixture_input_hash": file_sha256(input_manifest_path),
        "diagnostic_index_hash": diagnostic_index_receipt.file_hash,
        "diagnostic_window_count": len(diagnostic_index_records),
        "memory_semantic_payload_hash": memory_semantic_hash,
        "prediction_payload_hashes": [run.prediction_payload_hash for run in all_window_runs],
        "raw_b2_payload_hashes": [payload_hash(asdict(run.final_b2)) for run in all_window_runs],
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "retrieval_orders": [list(run.retrieval_order) for run in all_window_runs],
        "runtime_profile": RUNTIME_PROFILE,
        "semantic_mapping_identity": plan["base_evidence_mapper_identity"],
        "tool_policy": config.tool_policy,
        "video_order": [str(video["video_id"]) for video in fixture["videos"]],
        "videos": video_summaries,
        "window_traces": window_trace_records,
    }
    publisher.publish(
        "summary",
        dumps(semantic_summary),
        payload_hash(semantic_summary),
        parent_payload_hashes=(
            *(run.prediction_payload_hash for run in all_window_runs),
            *(payload_hash(asdict(run.final_b2)) for run in all_window_runs),
            memory_semantic_hash,
        ),
    )
    _output_manifest, output_receipt = publish_output_manifest(
        publisher,
        attempt_id=attempt_id,
        excluded_target_ids={"freeze:output", "freeze:memory", "freeze:inference"},
    )
    _memory_freeze, memory_receipt = publish_memory_freeze(
        publisher,
        namespace_id=config.memory_namespace_id,
        snapshot=final_snapshot,
        snapshot_path=config.memory_root / "memory_snapshot.json",
    )
    _inference_freeze, inference_receipt = publish_inference_freeze(
        publisher,
        attempt_id=attempt_id,
        prediction_freeze_hashes=tuple(prediction_freeze_hashes),
        output_manifest_hash=output_receipt.file_hash,
        memory_freeze_hash=memory_receipt.file_hash,
    )
    result = dict(semantic_summary)
    result.update(
        {
            "attempt_id": attempt_id,
            "freeze_hashes": {
                "inference": inference_receipt.file_hash,
                "memory": memory_receipt.file_hash,
                "output": output_receipt.file_hash,
            },
            "freeze_refs": {
                "output": "freezes/mvp_output_hash_manifest.json",
                "memory": "freezes/mvp_memory_freeze.json",
                "inference": "freezes/mvp_inference_freeze.json",
            },
            "memory_namespace_id": config.memory_namespace_id,
            "memory_snapshot_file_hash": file_sha256(config.memory_root / "memory_snapshot.json"),
            "memory_snapshot_path": str((config.memory_root / "memory_snapshot.json").resolve()),
            "output_attempt_root": str(output_attempt_root.resolve()),
        }
    )
    return result


def compare_semantic_runs(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "memory_semantic_payload_hash_equal": left["memory_semantic_payload_hash"] == right["memory_semantic_payload_hash"],
        "prediction_payload_hashes_equal": left["prediction_payload_hashes"] == right["prediction_payload_hashes"],
        "retrieval_orders_equal": left["retrieval_orders"] == right["retrieval_orders"],
    }
