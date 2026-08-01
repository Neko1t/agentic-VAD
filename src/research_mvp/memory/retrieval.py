from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from ..codec import payload_hash
from ..contracts import MvpAdvisoryPayload, MvpRetrievalKey, MvpRetrievalManifest
from .bm25 import bm25_view
from .dense import dense_view
from .rrf import VIEW_ORDER, rrf_order
from .temporal import temporal_view


@dataclass(frozen=True, slots=True)
class MvpRetrievalQuery:
    video_id: str
    window_id: str
    window_ordinal: int
    snapshot_payload_hash: str
    snapshot_version: int
    embedding: tuple[float, ...] | None
    tokens: tuple[str, ...]
    temporal_triples: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class MvpRankResult:
    manifest: MvpRetrievalManifest
    view_scores: tuple[tuple[str, tuple[tuple[str, float], ...]], ...]
    rrf_scores: tuple[tuple[str, float], ...]
    view_failures: tuple[tuple[str, str], ...] = ()


def _is_readable(query: MvpRetrievalQuery, case: MvpRetrievalKey) -> bool:
    if case.scope == "LONG_TERM":
        return case.source_video_id != query.video_id
    if case.scope == "SESSION":
        return (
            case.source_video_id == query.video_id
            and case.visible_from_window_ordinal is not None
            and case.visible_from_window_ordinal <= query.window_ordinal
        )
    return False


def rank_key_only(
    query: MvpRetrievalQuery,
    readable_cases: tuple[MvpRetrievalKey, ...],
    *,
    k_ret: int,
) -> MvpRankResult:
    cases = tuple(
        sorted(
            (case for case in readable_cases if _is_readable(query, case)),
            key=lambda item: (bytes.fromhex(item.key_hash), item.case_id.encode("utf-8")),
        )
    )
    if not cases:
        manifest = MvpRetrievalManifest(
            query_video_id=query.video_id,
            query_window_id=query.window_id,
            snapshot_payload_hash=query.snapshot_payload_hash,
            snapshot_version=query.snapshot_version,
            view_orders=(),
            rrf_order=(),
            ordered_top_k=(),
            payload_hashes=(),
        )
        return MvpRankResult(manifest, (), (), ())
    limit = min(3 * k_ret, len(cases))
    view_calls = {
        "DENSE": lambda: dense_view(query.embedding, cases, limit),
        "SPARSE_BM25": lambda: bm25_view(query.tokens, cases, limit),
        "TEMPORAL": lambda: temporal_view(query.temporal_triples, cases, limit),
    }
    computed: dict[str, tuple[tuple[str, float], ...] | None] = {}
    failures: list[tuple[str, str]] = []
    for name in VIEW_ORDER:
        try:
            computed[name] = view_calls[name]()
        except Exception:
            computed[name] = None
            failures.append((name, "MVP_RETRIEVAL_VIEW_FAILED"))
    view_scores = tuple((name, computed[name]) for name in VIEW_ORDER if computed[name] is not None)
    typed_view_scores = tuple((name, hits or ()) for name, hits in view_scores)
    by_id = {case.case_id: case for case in cases}
    fused = rrf_order(typed_view_scores, by_id, limit)
    top_k = tuple(case_id for case_id, _score in fused[: min(k_ret, len(fused))])
    manifest = MvpRetrievalManifest(
        query_video_id=query.video_id,
        query_window_id=query.window_id,
        snapshot_payload_hash=query.snapshot_payload_hash,
        snapshot_version=query.snapshot_version,
        view_orders=tuple((name, tuple(case_id for case_id, _ in hits)) for name, hits in typed_view_scores),
        rrf_order=tuple(case_id for case_id, _ in fused),
        ordered_top_k=top_k,
        payload_hashes=tuple((case_id, by_id[case_id].payload_hash) for case_id in top_k),
        view_failures=tuple(failures),
    )
    return MvpRankResult(manifest, typed_view_scores, fused, tuple(failures))


def accept_manifest(manifest: MvpRetrievalManifest, accepted_ref: str, accepted_file_hash: str) -> MvpRetrievalManifest:
    if manifest.accepted_ref is not None or manifest.accepted_file_hash is not None:
        raise ValueError("manifest is already accepted")
    if not accepted_ref or len(accepted_file_hash) != 64:
        raise ValueError("accepted manifest binding is incomplete")
    return replace(manifest, accepted_ref=accepted_ref, accepted_file_hash=accepted_file_hash)


class PayloadFirewall:
    def __init__(self, loader: Callable[[str], Mapping[str, Any]]) -> None:
        self._loader = loader

    def unlock(self, manifest: MvpRetrievalManifest) -> tuple[MvpAdvisoryPayload, ...]:
        if manifest.accepted_ref is None or manifest.accepted_file_hash is None:
            raise ValueError("payload unlock requires an accepted manifest")
        expected_hashes = dict(manifest.payload_hashes)
        unlocked: list[MvpAdvisoryPayload] = []
        for case_id in manifest.ordered_top_k:
            raw = dict(self._loader(case_id))
            if payload_hash(raw) != expected_hashes.get(case_id):
                raise ValueError("Advisory payload hash mismatch")
            if set(raw) != {"C", "R", "atom_ids", "d"}:
                raise ValueError("Advisory payload has an invalid field set")
            unlocked.append(
                MvpAdvisoryPayload(
                    case_id=case_id,
                    reliability=float(raw["R"]),
                    consistency=float(raw["C"]),
                    direction=float(raw["d"]),
                    atom_ids=tuple(str(value) for value in raw["atom_ids"]),
                )
            )
        return tuple(unlocked)
