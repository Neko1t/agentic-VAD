from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.research_mvp.memory.retrieval as retrieval_module
from src.research_mvp.contracts import MvpInterval, MvpObservedTemporalFact, MvpRetrievalKey
from src.research_mvp.memory.retrieval import (
    MvpRetrievalQuery,
    PayloadFirewall,
    accept_manifest,
    rank_key_only,
)
from src.research_mvp.memory.temporal import derive_allen_triples


GOLDEN = json.loads((Path(__file__).parent / "golden" / "expected_retrieval.json").read_bytes())


def key(
    case_id: str,
    *,
    embedding: tuple[float, ...],
    tokens: tuple[str, ...],
    triples: tuple[tuple[str, str, str], ...],
) -> MvpRetrievalKey:
    return MvpRetrievalKey(
        case_id=case_id,
        source_video_id="mvp-video-b-salient" if "-b-" in case_id else "mvp-video-a-reference",
        scope="LONG_TERM",
        key_hash=("b" if "-b-" in case_id else "a") * 64,
        payload_hash=GOLDEN["payload_hashes"][case_id],
        embedding=embedding,
        tokens=tokens,
        temporal_triples=triples,
    )


def cases() -> tuple[MvpRetrievalKey, ...]:
    return (
        key(
            "mvp-case-a-reference-0000",
            embedding=(1.0, 0.0, 0.0),
            tokens=("empty", "hallway", "quiet"),
            triples=(("person", "before", "walk"),),
        ),
        key(
            "mvp-case-b-salient-0000",
            embedding=(0.0, 1.0, 0.0),
            tokens=("alarm", "running", "smoke"),
            triples=(("alarm", "overlaps", "smoke"), ("person", "before", "alarm")),
        ),
    )


def query(*, embedding=(0.05, 0.99, 0.0), tokens=("alarm", "running", "smoke"), triples=None):
    return MvpRetrievalQuery(
        video_id="mvp-video-c-query",
        window_id="mvp-video-c-query-window-0000",
        window_ordinal=0,
        snapshot_payload_hash="1" * 64,
        snapshot_version=2,
        embedding=embedding,
        tokens=tokens,
        temporal_triples=triples
        if triples is not None
        else (("alarm", "overlaps", "smoke"), ("person", "before", "alarm")),
    )


def test_exact_three_view_and_rrf_orders_match_frozen_golden() -> None:
    result = rank_key_only(query(), cases(), k_ret=5)
    orders = dict(result.manifest.view_orders)

    assert list(orders) == GOLDEN["view_order"]
    assert list(orders["DENSE"]) == GOLDEN["views"]["DENSE"]
    assert list(orders["SPARSE_BM25"]) == GOLDEN["views"]["SPARSE_BM25"]
    assert list(orders["TEMPORAL"]) == GOLDEN["views"]["TEMPORAL"]
    assert list(result.manifest.rrf_order) == GOLDEN["rrf_order"]
    assert list(result.manifest.ordered_top_k) == GOLDEN["ordered_top_k"]


def test_dense_unavailable_uses_remaining_views_in_fixed_order() -> None:
    result = rank_key_only(query(embedding=None), cases(), k_ret=5)
    assert tuple(name for name, _ in result.manifest.view_orders) == ("SPARSE_BM25", "TEMPORAL")
    assert result.manifest.ordered_top_k[0] == "mvp-case-b-salient-0000"


def test_single_view_failure_is_recoverable_and_remaining_order_is_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_dense(*args, **kwargs):
        raise RuntimeError("private backend detail")

    monkeypatch.setattr(retrieval_module, "dense_view", fail_dense)

    result = rank_key_only(query(), cases(), k_ret=5)

    assert result.view_failures == (("DENSE", "MVP_RETRIEVAL_VIEW_FAILED"),)
    assert result.manifest.view_failures == result.view_failures
    assert tuple(name for name, _ in result.manifest.view_orders) == ("SPARSE_BM25", "TEMPORAL")
    assert result.manifest.ordered_top_k[0] == "mvp-case-b-salient-0000"


def test_all_view_failures_produce_empty_manifest_in_fixed_failure_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_view(*args, **kwargs):
        raise RuntimeError("private backend detail")

    monkeypatch.setattr(retrieval_module, "dense_view", fail_view)
    monkeypatch.setattr(retrieval_module, "bm25_view", fail_view)
    monkeypatch.setattr(retrieval_module, "temporal_view", fail_view)

    result = rank_key_only(query(), cases(), k_ret=5)

    assert result.manifest.ordered_top_k == ()
    assert result.view_failures == tuple(
        (name, "MVP_RETRIEVAL_VIEW_FAILED")
        for name in ("DENSE", "SPARSE_BM25", "TEMPORAL")
    )


def test_all_views_unavailable_produces_empty_manifest() -> None:
    result = rank_key_only(query(embedding=None, tokens=(), triples=()), (), k_ret=5)
    assert result.manifest.view_orders == ()
    assert result.manifest.ordered_top_k == ()


def test_payload_is_locked_until_manifest_acceptance_and_only_top_k_unlocks() -> None:
    poison_reads: list[str] = []
    payloads = {
        "mvp-case-a-reference-0000": {
            "C": 0.9999999999999998,
            "R": 0.8,
            "atom_ids": ["mvp-atom-a-0000", "mvp-atom-a-0001", "mvp-atom-a-0002"],
            "d": -1.0,
        },
        "mvp-case-b-salient-0000": {
            "C": 0.9999999999999998,
            "R": 0.8999999999999999,
            "atom_ids": ["mvp-atom-b-0000", "mvp-atom-b-0001", "mvp-atom-b-0002"],
            "d": 1.0,
        },
        "mvp-case-poison-0000": {"C": 1.0, "R": 1.0, "atom_ids": ["poison"], "d": 1.0},
    }

    def load_payload(case_id: str):
        poison_reads.append(case_id)
        return payloads[case_id]

    firewall = PayloadFirewall(load_payload)
    ranked = rank_key_only(query(), cases(), k_ret=1).manifest
    assert poison_reads == []
    with pytest.raises(ValueError, match="accepted manifest"):
        firewall.unlock(ranked)
    assert poison_reads == []

    accepted = accept_manifest(ranked, "retrieval_manifests/c/window.json", "f" * 64)
    bundle = firewall.unlock(accepted)

    assert tuple(item.case_id for item in bundle) == ("mvp-case-b-salient-0000",)
    assert poison_reads == ["mvp-case-b-salient-0000"]


def test_current_video_long_term_case_is_excluded_from_readable_scope() -> None:
    self_case = MvpRetrievalKey(
        case_id="mvp-case-c-query-salient-0000",
        source_video_id="mvp-video-c-query",
        scope="LONG_TERM",
        key_hash="0" * 64,
        payload_hash="0" * 64,
        embedding=(0.0, 1.0, 0.0),
        tokens=("alarm",),
        temporal_triples=(("person", "before", "alarm"),),
    )
    result = rank_key_only(query(), (*cases(), self_case), k_ret=5)
    assert self_case.case_id not in result.manifest.ordered_top_k


def test_same_video_closed_session_is_readable_only_from_visible_ordinal() -> None:
    session = MvpRetrievalKey(
        case_id="mvp-session-case-c-reference-0000",
        source_video_id="mvp-video-c-query",
        scope="SESSION",
        key_hash="0" * 64,
        payload_hash="0" * 64,
        embedding=(0.0, 1.0, 0.0),
        tokens=("alarm", "running", "smoke"),
        temporal_triples=(("alarm", "overlaps", "smoke"),),
        visible_from_window_ordinal=2,
    )

    before_visible = rank_key_only(query(), (*cases(), session), k_ret=5)
    visible_query = query()
    visible_query = retrieval_module.replace(visible_query, window_ordinal=2)
    after_visible = rank_key_only(visible_query, (*cases(), session), k_ret=5)

    assert session.case_id not in before_visible.manifest.ordered_top_k
    assert session.case_id in after_visible.manifest.ordered_top_k


def test_allen_triples_are_derived_only_from_observed_int64_intervals() -> None:
    facts = (
        MvpObservedTemporalFact("person", MvpInterval(0, 100)),
        MvpObservedTemporalFact("alarm", MvpInterval(200, 800)),
        MvpObservedTemporalFact("smoke", MvpInterval(400, 900)),
    )

    triples = derive_allen_triples(facts)

    assert ("person", "before", "alarm") in triples
    assert ("alarm", "after", "person") in triples
    assert ("alarm", "overlaps", "smoke") in triples
    assert ("smoke", "overlapped_by", "alarm") in triples
    assert derive_allen_triples((facts[0],)) == ()
