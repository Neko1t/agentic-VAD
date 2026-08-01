from __future__ import annotations

import json
from pathlib import Path

from src.research_mvp.artifacts.publisher import MvpImmutablePublisher
from src.research_mvp.codec import payload_hash
from src.research_mvp.runtime.inference_freeze import publish_output_manifest
from src.research_mvp.launcher import run_paired_smoke
from src.research_mvp.runtime.video_runner import compare_semantic_runs, run_synthetic_inference


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"


def test_fresh_attempt_reproducibility_excludes_attempt_envelopes(tmp_path: Path) -> None:
    left = run_synthetic_inference(
        attempt_id="mvp-repro-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    right = run_synthetic_inference(
        attempt_id="mvp-repro-b",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )

    comparison = compare_semantic_runs(left, right)

    assert comparison["prediction_payload_hashes_equal"] is True
    assert comparison["retrieval_orders_equal"] is True
    assert comparison["memory_semantic_payload_hash_equal"] is True
    assert left["attempt_id"] != right["attempt_id"]
    assert left["memory_namespace_id"] == left["attempt_id"]
    assert right["memory_namespace_id"] == right["attempt_id"]
    assert left["memory_snapshot_file_hash"] != right["memory_snapshot_file_hash"]


def test_memory_enabled_disabled_pair_shares_raw_inputs_without_claim_threshold(tmp_path: Path) -> None:
    comparison = run_paired_smoke(tmp_path, "mvp-paired-test", FIXTURE)

    assert comparison["fixture_input_hash_equal"] is True
    assert comparison["raw_b2_payload_hashes_equal"] is True
    assert comparison["status_code"] == "PAIRED_SMOKE_COMPLETED"
    assert comparison["research_claim_status"] == "NO_RESEARCH_CLAIM"
    assert not any("threshold" in key.casefold() or "improvement" in key.casefold() for key in comparison)
    enabled_snapshot = json.loads(
        (tmp_path / "data" / "agentic_memory" / "mvp" / comparison["enabled_attempt_id"] / "memory_snapshot.json").read_bytes()
    )
    disabled_snapshot = json.loads(
        (tmp_path / "data" / "agentic_memory" / "mvp" / comparison["disabled_attempt_id"] / "memory_snapshot.json").read_bytes()
    )
    assert enabled_snapshot["version"] == 3
    assert len(enabled_snapshot["cases"]) == 3
    assert disabled_snapshot["version"] == 0
    assert disabled_snapshot["cases"] == []


def test_output_manifest_semantic_hash_excludes_attempt_envelope(tmp_path: Path) -> None:
    hashes: list[str] = []
    for attempt_id in ("mvp-envelope-a", "mvp-envelope-b"):
        publisher = MvpImmutablePublisher(
            tmp_path / attempt_id,
            {"fact": "fact.json", "freeze:output": "output.json"},
        )
        fact = b'{"fact":1}'
        publisher.publish("fact", fact, payload_hash({"fact": 1}), parent_payload_hashes=("1" * 64,))
        manifest, _ = publish_output_manifest(
            publisher,
            attempt_id=attempt_id,
            excluded_target_ids={"freeze:output"},
        )
        hashes.append(manifest.payload_hash)

    assert hashes[0] == hashes[1]
