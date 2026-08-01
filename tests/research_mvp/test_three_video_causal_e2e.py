from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_mvp.artifacts.publisher import MvpImmutablePublisher
from src.research_mvp.codec import payload_hash
from src.research_mvp.failures import MvpFailure
from src.research_mvp.runtime.video_runner import run_synthetic_inference


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"
GOLDEN = json.loads((REPO_ROOT / "tests" / "research_mvp" / "golden" / "expected_retrieval.json").read_bytes())


def test_immutable_publisher_is_no_clobber_and_accepts_only_planned_targets(tmp_path: Path) -> None:
    publisher = MvpImmutablePublisher(tmp_path / "inference", {"artifact": "facts/artifact.json"})
    candidate = b'{"fact":1}'
    receipt = publisher.publish("artifact", candidate, payload_hash({"fact": 1}))

    assert receipt.accepted is True
    assert receipt.relative_ref == "facts/artifact.json"
    assert publisher.is_accepted("artifact")
    with pytest.raises(Exception):
        publisher.publish("artifact", candidate, payload_hash({"fact": 1}))
    with pytest.raises(Exception):
        publisher.publish("unplanned", candidate, payload_hash({"fact": 1}))


def test_three_video_causal_chain_and_freezes(tmp_path: Path) -> None:
    summary = run_synthetic_inference(
        attempt_id="mvp-e2e-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )

    assert summary["runtime_profile"] == "RESEARCH_MVP"
    assert summary["research_claim_status"] == "NO_RESEARCH_CLAIM"
    assert summary["video_order"] == [
        "mvp-video-a-reference",
        "mvp-video-b-salient",
        "mvp-video-c-query",
    ]
    expected_chain = [
        "B2_FINAL",
        "RETRIEVAL_MANIFEST_ACCEPTED",
        "PAYLOAD_UNLOCKED",
        "B6_FINAL",
        "B4_COMMITTED",
        "WINDOW_ARTIFACT_ACCEPTED",
        "EPISODE_UPDATED",
    ]
    for trace in summary["window_traces"]:
        assert trace["causal_chain"] == expected_chain
        assert trace["final_b2_count"] == 1
        assert trace["final_b6_count"] == 1
        assert trace["b4_commit_count"] == 1
        assert trace["window_artifact_count"] == 1
        assert trace["payload_read_after_manifest_acceptance"] is True

    b_video = summary["videos"][1]
    assert all("mvp-case-b-salient-0000" not in order for order in b_video["retrieval_orders"])
    assert b_video["memory_commit_count_at_video_start"] == b_video["memory_commit_count_before_prediction_freeze"]
    assert b_video["memory_commit_count_before_prediction_freeze"] == 1
    assert b_video["memory_commit_count_after_prediction_freeze"] == 2

    c_video = summary["videos"][2]
    assert c_video["retrieval_orders"][0] == GOLDEN["ordered_top_k"]
    assert c_video["view_orders"][0] == GOLDEN["views"]
    assert c_video["retrieval_orders"][0][0] == "mvp-case-b-salient-0000"
    c_manifest_path = (
        Path(summary["output_attempt_root"])
        / "inference"
        / "retrieval_manifests"
        / "mvp-video-c-query"
        / "mvp-video-c-query-window-0000.json"
    )
    c_manifest = json.loads(c_manifest_path.read_bytes())
    assert dict(c_manifest["payload_hashes"]) == GOLDEN["payload_hashes"]

    snapshot = json.loads(Path(summary["memory_snapshot_path"]).read_bytes())
    by_id = {case["case_id"]: case for case in snapshot["cases"]}
    assert "mvp-case-b-salient-0000" in by_id
    assert by_id["mvp-case-b-salient-0000"]["derivation"] == "LOCAL_FINAL_B2_ONLY"
    assert by_id["mvp-case-b-salient-0000"]["source_prediction_freeze_hash"] == b_video["prediction_freeze_hash"]
    assert summary["freeze_refs"] == {
        "output": "freezes/mvp_output_hash_manifest.json",
        "memory": "freezes/mvp_memory_freeze.json",
        "inference": "freezes/mvp_inference_freeze.json",
    }


def test_incomplete_video_does_not_write_memory(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_bytes())
    fixture["videos"][0]["windows"][1]["ordinal"] = 99
    broken = tmp_path / "broken-input.json"
    broken.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(Exception):
        run_synthetic_inference(
            attempt_id="mvp-broken-a",
            project_root=tmp_path,
            fixture_path=broken,
            memory_enabled=True,
        )
    snapshot_path = tmp_path / "data" / "agentic_memory" / "mvp" / "mvp-broken-a" / "memory_snapshot.json"
    assert json.loads(snapshot_path.read_bytes())["version"] == 0


def test_memory_failure_stops_before_next_video(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        run_synthetic_inference(
            attempt_id="mvp-memory-fail-a",
            project_root=tmp_path,
            fixture_path=FIXTURE,
            memory_enabled=True,
            memory_fault_video_id="mvp-video-b-salient",
        )
    attempt = tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-memory-fail-a" / "inference"
    assert not (attempt / "window_artifacts" / "mvp-video-c-query").exists()
    snapshot_path = tmp_path / "data" / "agentic_memory" / "mvp" / "mvp-memory-fail-a" / "memory_snapshot.json"
    snapshot = json.loads(snapshot_path.read_bytes())
    assert snapshot["version"] == 1
    assert snapshot["last_committed_video_id"] == "mvp-video-a-reference"


def test_snapshot_unavailable_seals_current_identity_prediction_then_stops(tmp_path: Path) -> None:
    with pytest.raises(MvpFailure, match="MVP_MEMORY_UNAVAILABLE"):
        run_synthetic_inference(
            attempt_id="mvp-memory-read-fail-a",
            project_root=tmp_path,
            fixture_path=FIXTURE,
            memory_enabled=True,
            memory_read_fault_at=("mvp-video-b-salient", 0),
        )

    inference = tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-memory-read-fail-a" / "inference"
    sealed_window = inference / "window_artifacts" / "mvp-video-b-salient" / "mvp-video-b-salient-window-0000.json"
    sealed_predictions = inference / "predictions" / "mvp-video-b-salient.jsonl"
    sealed = json.loads(sealed_window.read_bytes())
    assert sealed["memory_status"] == "MVP_MEMORY_UNAVAILABLE"
    assert len(sealed_predictions.read_bytes().splitlines()) == 1
    assert not (inference / "freezes" / "prediction" / "mvp-video-b-salient.json").exists()
    assert not (inference / "window_artifacts" / "mvp-video-b-salient" / "mvp-video-b-salient-window-0001.json").exists()
    assert not (inference / "window_artifacts" / "mvp-video-c-query").exists()
    snapshot = json.loads(
        (tmp_path / "data" / "agentic_memory" / "mvp" / "mvp-memory-read-fail-a" / "memory_snapshot.json").read_bytes()
    )
    assert snapshot["version"] == 1
    assert snapshot["last_committed_video_id"] == "mvp-video-a-reference"


def test_output_manifest_records_real_causal_parent_payload_hashes(tmp_path: Path) -> None:
    summary = run_synthetic_inference(
        attempt_id="mvp-parent-graph-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    inference = Path(summary["output_attempt_root"]) / "inference"
    manifest = json.loads((inference / "freezes" / "mvp_output_hash_manifest.json").read_bytes())
    entries = {entry["relative_ref"]: entry for entry in manifest["entries"]}
    assert entries["mvp_inference_plan.json"]["parent_payload_hashes"]
    window_ref = "window_artifacts/mvp-video-c-query/mvp-video-c-query-window-0000.json"
    window = json.loads((inference / window_ref).read_bytes())
    assert set(entries[window_ref]["parent_payload_hashes"]) == {
        window["final_b2_payload_hash"],
        window["retrieval_manifest_payload_hash"],
        window["final_b6_payload_hash"],
        window["b4_payload_hash"],
    }
    assert all(
        len(parent_hash) == 64
        for entry in manifest["entries"]
        for parent_hash in entry["parent_payload_hashes"]
    )


def test_inference_plan_freezes_runtime_packages_sampling_and_raw_outputs(tmp_path: Path) -> None:
    summary = run_synthetic_inference(
        attempt_id="mvp-provenance-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    plan = json.loads((Path(summary["output_attempt_root"]) / "inference" / "mvp_inference_plan.json").read_bytes())

    assert len(plan["python_executable_sha256"]) == 64
    assert plan["installed_package_file_hashes"]
    assert plan["model_sampling"] == {
        "deterministic_precomputed": True,
        "seed": 0,
        "temperature": 0.0,
        "top_p": 1.0,
    }
    assert len(plan["raw_output_artifacts"]) == 8
    assert all(len(item["payload_hash"]) == 64 for item in plan["raw_output_artifacts"])
