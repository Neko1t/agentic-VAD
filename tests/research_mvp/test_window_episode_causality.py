from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_mvp.contracts import MvpB2Output, MvpEpisode
from src.research_mvp.memory.episode import EpisodeBuilder, MvpEpisodeWindow, summarize_episode
from src.research_mvp.runtime.video_runner import run_synthetic_inference


def test_episode_updates_require_accepted_window_artifact() -> None:
    builder = EpisodeBuilder("mvp-video-b-salient")
    with pytest.raises(ValueError, match="accepted WindowArtifact"):
        builder.feed(0, "NORMAL", artifact_accepted=False)
    assert builder.next_window_ordinal == 0


def test_session_is_closed_same_video_and_later_window_only() -> None:
    builder = EpisodeBuilder("mvp-video-b-salient")
    builder.feed(0, "NORMAL", artifact_accepted=True)
    builder.feed(1, "ABNORMAL", artifact_accepted=True)

    closed = builder.closed_episodes
    assert len(closed) == 1
    reference = closed[0]
    assert reference.role == "REFERENCE"
    assert reference.visible_from_window_ordinal == 1
    assert builder.readable_sessions("mvp-video-b-salient", 0) == ()
    assert builder.readable_sessions("mvp-video-b-salient", 1) == (reference,)
    assert builder.readable_sessions("mvp-video-c-query", 99) == ()


def test_open_current_and_future_episode_are_not_retrievable() -> None:
    builder = EpisodeBuilder("mvp-video-b-salient")
    builder.feed(0, "ABNORMAL", artifact_accepted=True)
    builder.feed(1, "ABNORMAL", artifact_accepted=True)

    assert builder.closed_episodes == ()
    assert builder.readable_sessions("mvp-video-b-salient", 2) == ()

    episodes = builder.close_video()
    salient = episodes[0]
    assert salient.closed is True
    assert salient.visible_from_window_ordinal == 2
    assert salient.core_window_ordinals == (0, 1)
    assert builder.readable_sessions("mvp-video-b-salient", 2) == ()


def test_window_order_violation_is_attempt_fatal_boundary() -> None:
    builder = EpisodeBuilder("mvp-video-a-reference")
    builder.feed(0, "NORMAL", artifact_accepted=True)
    with pytest.raises(ValueError, match="window order"):
        builder.feed(0, "NORMAL", artifact_accepted=True)


def _local_b2(
    ordinal: int,
    *,
    quality: float,
    direction: float,
    embedding: tuple[float, ...],
    token: str,
) -> MvpB2Output:
    evidence = quality * direction
    return MvpB2Output(
        video_id="mvp-video-summary",
        window_id=f"mvp-video-summary-window-{ordinal:04d}",
        window_ordinal=ordinal,
        slot="B2:final",
        positive=max(evidence, 0.0),
        negative=max(-evidence, 0.0),
        quality=quality,
        direction=direction,
        conflict=0.0,
        e_local=evidence,
        u_local=1.0 - abs(evidence),
        modalities=(),
        assessment_ids=(f"assessment-{ordinal}",),
        supporting_atom_ids=(f"atom-{ordinal}",) if evidence > 0.0 else (),
        counter_atom_ids=(f"atom-{ordinal}",) if evidence < 0.0 else (),
        fact_tokens=(token,),
        embedding=embedding,
    )


def test_episode_m2_uses_delta_weighted_local_final_b2_only() -> None:
    episode = MvpEpisode(
        episode_id="mvp-episode-summary-salient-0000",
        video_id="mvp-video-summary",
        role="SALIENT",
        ordinal=0,
        core_window_ordinals=(0, 1),
        member_window_ordinals=(0, 1),
        closed=True,
        visible_from_window_ordinal=2,
    )
    windows = (
        MvpEpisodeWindow(0, "w0", 1, _local_b2(0, quality=0.4, direction=0.5, embedding=(1.0, 0.0), token="first")),
        MvpEpisodeWindow(1, "w1", 3, _local_b2(1, quality=0.8, direction=1.0, embedding=(0.0, 1.0), token="second")),
    )

    summary = summarize_episode(episode, windows)

    assert summary.reliability == pytest.approx(0.7)
    assert summary.direction == pytest.approx(0.65 / 0.7)
    assert summary.uncertainty == pytest.approx(0.35)
    assert summary.consistency == pytest.approx(0.65 / (0.05 + 0.6 + 2.0**-52))
    assert summary.atom_ids == ("atom-0", "atom-1")


def test_reference_m1_uses_semantic_medoid_facts_and_embedding() -> None:
    episode = MvpEpisode(
        episode_id="mvp-episode-summary-reference-0000",
        video_id="mvp-video-summary",
        role="REFERENCE",
        ordinal=0,
        core_window_ordinals=(0, 1, 2),
        member_window_ordinals=(0, 1, 2),
        closed=True,
        visible_from_window_ordinal=3,
    )
    windows = (
        MvpEpisodeWindow(0, "w0", 1, _local_b2(0, quality=0.5, direction=-1.0, embedding=(1.0, 0.0), token="edge-a")),
        MvpEpisodeWindow(1, "w1", 1, _local_b2(1, quality=0.5, direction=-1.0, embedding=(0.8, 0.6), token="medoid")),
        MvpEpisodeWindow(2, "w2", 1, _local_b2(2, quality=0.5, direction=-1.0, embedding=(0.0, 1.0), token="edge-b")),
    )

    summary = summarize_episode(episode, windows)

    assert summary.medoid_window_id == "w1"
    assert summary.embedding == (0.8, 0.6)
    assert summary.tokens == ("medoid",)


def test_composition_root_publishes_closed_episode_session_for_later_window(tmp_path: Path) -> None:
    def window(ordinal: int, direction: float, quality: float) -> dict[str, object]:
        start = ordinal * 1_000_000
        return {
            "window_id": f"mvp-video-session-flow-window-{ordinal:04d}",
            "ordinal": ordinal,
            "start_us": start,
            "end_us": start + 1_000_000,
            "delta_us": 1_000_000,
            "direction": direction,
            "quality": quality,
            "embedding": [1.0, 0.0],
            "tokens": ["session", "corridor"],
            "temporal_facts": [
                {"fact_id": "person", "start_us": start, "end_us": start + 300_000},
                {"fact_id": "walk", "start_us": start + 600_000, "end_us": start + 900_000},
            ],
        }

    fixture = {
        "fixture_id": "mvp-session-causal-v0",
        "runtime_profile": "RESEARCH_MVP",
        "static_max_case_count": 2,
        "videos": [
            {
                "video_id": "mvp-video-session-flow",
                "windows": [window(0, -1.0, 1.0), window(1, 1.0, 1.0), window(2, 0.2, 0.4)],
            }
        ],
    }
    fixture_path = tmp_path / "session-input.json"
    fixture_path.write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")

    summary = run_synthetic_inference(
        attempt_id="mvp-session-flow-a",
        project_root=tmp_path,
        fixture_path=fixture_path,
        memory_enabled=True,
    )

    third_order = summary["videos"][0]["retrieval_orders"][2]
    assert any(case_id.startswith("mvp-session-case-") for case_id in third_order)
    assert summary["videos"][0]["session_case_count"] == 1
