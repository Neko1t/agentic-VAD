from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Callable
from typing import Any, Mapping

from ..artifacts.publisher import MvpImmutablePublisher, MvpPublishReceipt
from ..codec import dumps, payload_hash
from ..contracts import MvpB2Output, MvpB4Commit, MvpEpisode, MvpInterval, MvpRetrievalKey, MvpWindowArtifact
from ..evidence.adapters import PrecomputedEvidenceAdapter
from ..evidence.b3_lite import MvpB3LiteResult, run_b3_lite
from ..math.b4 import B4Committer
from ..math.b6 import fuse_b6_detailed
from ..memory.episode import EpisodeBuilder
from ..memory.retrieval import MvpRetrievalQuery, PayloadFirewall, accept_manifest, rank_key_only
from .diagnostics import build_window_diagnostic


@dataclass(frozen=True, slots=True)
class MvpWindowRun:
    final_b2: MvpB2Output
    b3: MvpB3LiteResult
    b4: MvpB4Commit
    window_artifact: MvpWindowArtifact
    window_receipt: MvpPublishReceipt
    diagnostic: dict[str, Any]
    diagnostic_receipt: MvpPublishReceipt
    prediction_payload_hash: str
    prediction_record: dict[str, Any]
    retrieval_order: tuple[str, ...]
    view_orders: tuple[tuple[str, tuple[str, ...]], ...]
    retrieval_manifest_hash: str
    delta_us: int
    closed_episodes: tuple[MvpEpisode, ...]
    trace: dict[str, Any]


class _LazyActionArtifacts(Mapping[str, tuple[Mapping[str, Any] | None, str | None]]):
    def __init__(
        self,
        loader: Callable[[str], Mapping[str, Any]],
        artifact_refs: Mapping[str, Any],
    ) -> None:
        self._loader = loader
        self._refs = artifact_refs

    def __getitem__(self, action: str) -> tuple[Mapping[str, Any] | None, str | None]:
        if action not in {"OCR", "AUDIO"}:
            raise KeyError(action)
        return self._loader(action), str(self._refs[action]["payload_hash"])

    def __iter__(self):
        return iter(("OCR", "AUDIO"))

    def __len__(self) -> int:
        return 2


def _base_raw(video_id: str, window: Mapping[str, Any]) -> dict[str, Any]:
    suffix = video_id.removeprefix("mvp-video-").split("-", 1)[0]
    return {
        "observation_id": f"obs-{window['window_id']}-vlm",
        "source": "precomputed-vlm",
        "channel": "VLM",
        "family": "VISUAL",
        "status": "SUCCEEDED",
        "q_in": float(window["quality"]),
        "q_src": 1.0,
        "direction": float(window["direction"]),
        "observed_intervals": [{"start_us": window["start_us"], "end_us": window["end_us"]}],
        "risk_atom_ids": [f"mvp-atom-{suffix}-{window['ordinal']:04d}"],
        "atoms": [
            {
                "atom_id": f"mvp-atom-{suffix}-{window['ordinal']:04d}",
                "source_family": "VISUAL",
                "status": "VALID",
                "role": "RISK",
                "direction": float(window["direction"]),
                "validity_gate": 1,
                "q_in": float(window["quality"]),
                "q_src": 1.0,
                "interval": {"start_us": window["start_us"], "end_us": window["end_us"]},
                "fact_slot": [suffix, "observed", "window", "event"],
                "interpretation_trace": "direct refutation of the same suspicious explanation"
                if float(window["direction"]) < 0.0
                else None,
            }
        ],
        "fact_tokens": list(window["tokens"]),
        "embedding": list(window["embedding"]),
        "temporal_facts": [dict(item) for item in window.get("temporal_facts", ())],
    }


def case_capabilities(case: Mapping[str, Any]) -> tuple[MvpRetrievalKey, Mapping[str, Any]]:
    raw_key = case["retrieval_key"]
    case_id = str(case["case_id"])
    key = MvpRetrievalKey(
        case_id=case_id,
        source_video_id=str(case["source_video_id"]),
        scope=str(case["scope"]),
        key_hash=str(raw_key["key_hash"]),
        payload_hash=str(raw_key["payload_hash"]),
        embedding=None if raw_key["embedding"] is None else tuple(float(value) for value in raw_key["embedding"]),
        tokens=tuple(str(value) for value in raw_key["tokens"]),
        temporal_triples=tuple(tuple(str(part) for part in triple) for triple in raw_key["temporal_triples"]),
        visible_from_window_ordinal=raw_key.get("visible_from_window_ordinal"),
    )
    return key, case["advisory_payload"]


def _snapshot_capabilities(snapshot: Mapping[str, Any]) -> tuple[tuple[MvpRetrievalKey, ...], dict[str, Mapping[str, Any]]]:
    keys: list[MvpRetrievalKey] = []
    payloads: dict[str, Mapping[str, Any]] = {}
    for case in snapshot["cases"]:
        key, payload = case_capabilities(case)
        keys.append(key)
        payloads[key.case_id] = payload
    return tuple(keys), payloads


def run_window(
    *,
    video_id: str,
    window: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    publisher: MvpImmutablePublisher,
    b4_committer: B4Committer,
    episode_builder: EpisodeBuilder,
    memory_enabled: bool,
    session_keys: tuple[MvpRetrievalKey, ...] = (),
    session_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    memory_status_override: str | None = None,
    evidence_loader: Callable[[str], Mapping[str, Any]] | None = None,
    semantic_evidence_mapper: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
    semantic_score_manifest_sha256: str | None = None,
    tool_action_order: tuple[str, ...] = ("OCR", "AUDIO"),
) -> MvpWindowRun:
    ordinal = window["ordinal"]
    if isinstance(ordinal, bool) or not isinstance(ordinal, int):
        raise ValueError("window ordinal must be an integer")
    interval = MvpInterval(window["start_us"], window["end_us"])
    if window["delta_us"] <= 0:
        raise ValueError("delta_us must be positive")
    adapter = PrecomputedEvidenceAdapter()
    if evidence_loader is None:
        raw_base = _base_raw(video_id, window)
        base_hash = payload_hash(raw_base)
        action_artifacts: Mapping[str, tuple[Mapping[str, Any] | None, str | None]] = {}
    else:
        artifact_refs = window.get("evidence_artifacts")
        if not isinstance(artifact_refs, Mapping):
            raise ValueError("precomputed evidence registry is missing")
        raw_base = evidence_loader("VLM")
        source_base_hash = str(artifact_refs["VLM"]["payload_hash"])
        if semantic_evidence_mapper is not None:
            raw_base = semantic_evidence_mapper(video_id, window, raw_base)
        base_hash = source_base_hash
        if semantic_evidence_mapper is not None:
            base_hash = payload_hash(dict(raw_base))
        action_artifacts = _LazyActionArtifacts(evidence_loader, artifact_refs)
    base = adapter.accept("VLM", raw_base, base_hash)
    b3 = run_b3_lite(
        video_id=video_id,
        window_id=str(window["window_id"]),
        window_ordinal=ordinal,
        window=interval,
        base_results=(base,),
        action_artifacts=action_artifacts,
        adapter=adapter,
        action_order=tool_action_order,
    )
    final_b2 = b3.final_b2
    causal_chain = ["B2_FINAL"]

    long_term_keys, long_term_payloads = _snapshot_capabilities(snapshot)
    all_keys = (*long_term_keys, *session_keys) if memory_enabled and memory_status_override is None else ()
    all_payloads = dict(long_term_payloads)
    all_payloads.update(session_payloads or {})
    query = MvpRetrievalQuery(
        video_id=video_id,
        window_id=str(window["window_id"]),
        window_ordinal=ordinal,
        snapshot_payload_hash=str(snapshot["payload_hash"]),
        snapshot_version=int(snapshot["version"]),
        embedding=final_b2.embedding,
        tokens=final_b2.fact_tokens,
        temporal_triples=final_b2.temporal_triples,
    )
    ranked = rank_key_only(query, tuple(all_keys), k_ret=5)
    final_b2_hash = payload_hash(asdict(final_b2))
    manifest_bytes = dumps(asdict(ranked.manifest))
    manifest_receipt = publisher.publish(
        f"manifest:{video_id}:{window['window_id']}",
        manifest_bytes,
        payload_hash(asdict(ranked.manifest)),
        parent_payload_hashes=(
            final_b2_hash,
            str(snapshot["payload_hash"]),
            *(key.key_hash for key in all_keys),
        ),
    )
    manifest = accept_manifest(ranked.manifest, manifest_receipt.relative_ref, manifest_receipt.file_hash)
    causal_chain.append("RETRIEVAL_MANIFEST_ACCEPTED")
    manifest_accepted = True
    payload_reads: list[tuple[str, bool]] = []

    def load_payload(case_id: str) -> Mapping[str, Any]:
        payload_reads.append((case_id, manifest_accepted))
        return all_payloads[case_id]

    bundle = PayloadFirewall(load_payload).unlock(manifest)
    causal_chain.append("PAYLOAD_UNLOCKED")
    b6_result = fuse_b6_detailed(
        final_b2,
        bundle,
        memory_enabled=True if memory_status_override is not None else memory_enabled,
        empty_status=memory_status_override or "EMPTY_IDENTITY",
    )
    final_b6 = b6_result.output
    causal_chain.append("B6_FINAL")
    b4_result = b4_committer.commit_with_audit(
        video_id,
        str(window["window_id"]),
        ordinal,
        int(window["delta_us"]),
        final_b2,
        final_b6,
    )
    b4 = b4_result.commit
    causal_chain.append("B4_COMMITTED")
    prediction_payload = {
        "prediction": b4.z,
        "video_id": video_id,
        "window_id": str(window["window_id"]),
        "window_ordinal": ordinal,
    }
    decision_fields = {"end_frame", "frame_count", "frame_interval", "start_frame"}
    if decision_fields.issubset(window):
        prediction_payload.update(
            {
                "end_frame": int(window["end_frame"]),
                "frame_count": int(window["frame_count"]),
                "frame_interval": int(window["frame_interval"]),
                "start_frame": int(window["start_frame"]),
            }
        )
    prediction_hash = payload_hash(prediction_payload)
    artifact = MvpWindowArtifact(
        video_id=video_id,
        window_id=str(window["window_id"]),
        window_ordinal=ordinal,
        final_b2_payload_hash=payload_hash(asdict(final_b2)),
        retrieval_manifest_payload_hash=manifest_receipt.payload_hash,
        final_b6_payload_hash=payload_hash(asdict(final_b6)),
        b4_payload_hash=payload_hash(asdict(b4)),
        prediction=b4.z,
        memory_status=final_b6.memory_status,
    )
    artifact_bytes = dumps(asdict(artifact))
    artifact_receipt = publisher.publish(
        f"window:{video_id}:{window['window_id']}",
        artifact_bytes,
        payload_hash(asdict(artifact)),
        parent_payload_hashes=(
            artifact.final_b2_payload_hash,
            artifact.retrieval_manifest_payload_hash,
            artifact.final_b6_payload_hash,
            artifact.b4_payload_hash,
        ),
    )
    causal_chain.append("WINDOW_ARTIFACT_ACCEPTED")
    diagnostic = build_window_diagnostic(
        window=window,
        base_result=base,
        b3=b3,
        b6=final_b6,
        b6_audit=b6_result.audit,
        b4=b4,
        b4_audit=b4_result.audit,
        window_artifact=artifact,
        window_receipt=artifact_receipt,
        prediction_payload_hash=prediction_hash,
        base_evidence_is_derived=semantic_evidence_mapper is not None,
    )
    diagnostic_bytes = dumps(diagnostic)
    if semantic_evidence_mapper is None:
        diagnostic_evidence_parents = tuple(
            str(item["payload_hash"])
            for item in diagnostic["evidence_artifacts"]
            if item["payload_hash"] is not None
        )
    else:
        if semantic_score_manifest_sha256 is None:
            raise ValueError("derived semantic evidence requires its manifest hash")
        diagnostic_evidence_parents = (
            base.raw_payload_hash,
            source_base_hash,
            semantic_score_manifest_sha256,
            *(
                str(item["payload_hash"])
                for item in diagnostic["evidence_artifacts"]
                if item["action"] != "VLM" and item["payload_hash"] is not None
            ),
        )
    diagnostic_parents = (artifact_receipt.file_hash, *diagnostic_evidence_parents)
    diagnostic_receipt = publisher.publish(
        f"diagnostic-window:{video_id}:{window['window_id']}",
        diagnostic_bytes,
        payload_hash(diagnostic),
        parent_payload_hashes=diagnostic_parents,
    )
    closed_episodes = episode_builder.feed(ordinal, b4.state, artifact_accepted=artifact_receipt.accepted)
    causal_chain.append("EPISODE_UPDATED")
    trace = {
        "video_id": video_id,
        "window_id": str(window["window_id"]),
        "window_ordinal": ordinal,
        "causal_chain": causal_chain,
        "final_b2_count": sum(1 for output in b3.b2_outputs if output.slot == "B2:final"),
        "final_b6_count": 1,
        "b4_commit_count": 1,
        "window_artifact_count": 1,
        "diagnostic_artifact_count": 1,
        "payload_read_after_manifest_acceptance": manifest_accepted and all(accepted for _, accepted in payload_reads),
        "payload_read_case_ids": [case_id for case_id, _ in payload_reads],
        "memory_status": final_b6.memory_status,
    }
    return MvpWindowRun(
        final_b2=final_b2,
        b3=b3,
        b4=b4,
        window_artifact=artifact,
        window_receipt=artifact_receipt,
        diagnostic=diagnostic,
        diagnostic_receipt=diagnostic_receipt,
        prediction_payload_hash=prediction_hash,
        prediction_record=prediction_payload,
        retrieval_order=manifest.ordered_top_k,
        view_orders=manifest.view_orders,
        retrieval_manifest_hash=manifest_receipt.file_hash,
        delta_us=int(window["delta_us"]),
        closed_episodes=closed_episodes,
        trace=trace,
    )
