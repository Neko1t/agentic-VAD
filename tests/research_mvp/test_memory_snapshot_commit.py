from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_mvp.failures import MvpFailure
from src.research_mvp.memory.snapshot import MvpMemoryWriter, read_snapshot


def candidate(case_id: str, video_id: str, freeze_hash: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "source_video_id": video_id,
        "scope": "LONG_TERM",
        "derivation": "LOCAL_FINAL_B2_ONLY",
        "source_prediction_freeze_hash": freeze_hash,
        "retrieval_key": {
            "embedding": [0.0, 1.0],
            "tokens": ["alarm"],
            "temporal_triples": [["person", "before", "alarm"]],
        },
        "advisory_payload": {"C": 1.0, "R": 0.9, "atom_ids": ["atom"], "d": 1.0},
    }


def test_genesis_requires_fresh_namespace_and_snapshot_is_only_truth(tmp_path: Path) -> None:
    root = tmp_path / "mvp-attempt"
    writer = MvpMemoryWriter.create_fresh(root, "mvp-attempt")
    snapshot = read_snapshot(root)

    assert snapshot["version"] == 0
    assert snapshot["namespace_id"] == "mvp-attempt"
    assert snapshot["cases"] == []
    assert (root / "memory_snapshot.json").is_file()
    assert not (root / "audit" / "video_commits.jsonl").exists()
    with pytest.raises(MvpFailure):
        MvpMemoryWriter.create_fresh(root, "mvp-attempt")
    assert writer.commit_count == 0


def test_commit_is_after_prediction_freeze_and_atomic(tmp_path: Path) -> None:
    root = tmp_path / "mvp-attempt"
    writer = MvpMemoryWriter.create_fresh(root, "mvp-attempt")
    freeze_hash = "1" * 64

    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        writer.commit_video(
            video_id="mvp-video-b-salient",
            prediction_freeze_hash=freeze_hash,
            prediction_freeze_accepted=False,
            candidates=(candidate("mvp-case-b-salient-0000", "mvp-video-b-salient", freeze_hash),),
        )
    assert read_snapshot(root)["version"] == 0

    committed = writer.commit_video(
        video_id="mvp-video-b-salient",
        prediction_freeze_hash=freeze_hash,
        prediction_freeze_accepted=True,
        candidates=(candidate("mvp-case-b-salient-0000", "mvp-video-b-salient", freeze_hash),),
    )
    assert committed["version"] == 1
    assert committed["last_committed_video_id"] == "mvp-video-b-salient"
    assert writer.commit_count == 1
    projection = root / "audit" / "video_commits.jsonl"
    assert json.loads(projection.read_text(encoding="utf-8"))["snapshot_payload_hash"] == committed["payload_hash"]


def test_fault_before_replace_preserves_old_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "mvp-attempt"
    writer = MvpMemoryWriter.create_fresh(root, "mvp-attempt")
    before = (root / "memory_snapshot.json").read_bytes()

    def fault(stage: str) -> None:
        if stage == "before_replace":
            raise OSError("injected")

    with pytest.raises(MvpFailure, match="MVP_MEMORY_COMMIT_FAILED"):
        writer.commit_video(
            video_id="mvp-video-a-reference",
            prediction_freeze_hash="1" * 64,
            prediction_freeze_accepted=True,
            candidates=(candidate("mvp-case-a-reference-0000", "mvp-video-a-reference", "1" * 64),),
            fault_injector=fault,
        )
    assert (root / "memory_snapshot.json").read_bytes() == before
    assert read_snapshot(root)["version"] == 0


def test_fault_after_replace_keeps_new_snapshot_and_reports_projection_failure(tmp_path: Path) -> None:
    root = tmp_path / "mvp-attempt"
    writer = MvpMemoryWriter.create_fresh(root, "mvp-attempt")

    def fault(stage: str) -> None:
        if stage == "before_audit":
            raise OSError("injected")

    with pytest.raises(MvpFailure, match="MVP_MEMORY_AUDIT_INCOMPLETE"):
        writer.commit_video(
            video_id="mvp-video-a-reference",
            prediction_freeze_hash="1" * 64,
            prediction_freeze_accepted=True,
            candidates=(candidate("mvp-case-a-reference-0000", "mvp-video-a-reference", "1" * 64),),
            fault_injector=fault,
        )
    assert read_snapshot(root)["version"] == 1
    assert writer.commit_count == 1


def test_capacity_fails_closed_before_replace(tmp_path: Path) -> None:
    root = tmp_path / "mvp-attempt"
    writer = MvpMemoryWriter.create_fresh(root, "mvp-attempt", capacity=1)
    before = (root / "memory_snapshot.json").read_bytes()
    freeze_hash = "1" * 64
    with pytest.raises(MvpFailure, match="MVP_CAPACITY_EXCEEDED"):
        writer.commit_video(
            video_id="mvp-video-b-salient",
            prediction_freeze_hash=freeze_hash,
            prediction_freeze_accepted=True,
            candidates=(
                candidate("case-1", "mvp-video-b-salient", freeze_hash),
                candidate("case-2", "mvp-video-b-salient", freeze_hash),
            ),
        )
    assert (root / "memory_snapshot.json").read_bytes() == before
