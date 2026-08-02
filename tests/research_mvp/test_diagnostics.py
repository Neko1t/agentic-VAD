from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.research_mvp.codec import payload_hash
from src.research_mvp.contracts import MvpAdvisoryPayload, MvpB2Output, MvpB6Output, MvpInterval, MvpModalityEvidence
from src.research_mvp.evidence.adapters import PrecomputedEvidenceAdapter
from src.research_mvp.evidence.b3_lite import run_b3_lite
from src.research_mvp.failures import MvpFailure
from src.research_mvp.launcher import run_outer_attempt, verify_frozen_attempt
from src.research_mvp.math.b4 import MvpB4State, compute_b4, compute_b4_detailed
from src.research_mvp.math.b6 import fuse_b6, fuse_b6_detailed
from src.research_mvp.runtime.video_runner import run_synthetic_inference


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"
BASELINE_PREDICTION_HASHES = (
    "b0f3f65bcc82b57a571c9744868333e405f7ebdccd52186c1e00b1dd942a5fd6",
    "a808e0337bfdcf6e3756aeaf5ea1d740348d48a97b54ca8630abfb3c2b725a1d",
    "a16adcb09cced9c2ef61ae90087d83e1d5e3197aad63d18d59db2c7aaeb090a5",
    "b012f998bbeb6ed4c2f7bd73c643a05565e795f408b638a6a8f41c771ba6e331",
    "4dc0edf0b636176425f6f0013aee95d89e78eb48226086ff6ea56f68b8764386",
    "b7c49300190a9fd29e57251ca3501e5ba128298a8a24ee3323fdd75c7e17625d",
    "759bd747bc8a4385cae587ffd75da299c76e6f9261d48ad1b6ff658d946f8aed",
    "83d1fd5c3be3e117c42a11fcedb28671320213bfa172430c17ad131e9a4fe36d",
)
FORBIDDEN_INFERENCE_KEYS = {"annotation", "ground_truth", "label", "metric_target", "target"}


def _artifact(action: str, *, direction: float, q_in: float, q_src: float) -> dict[str, Any]:
    channel = {"VLM": "VLM", "OCR": "OCR", "AUDIO": "ACOUSTIC_EVENT"}[action]
    family = "AUDIO" if action == "AUDIO" else "VISUAL"
    return {
        "observation_id": f"obs-{action.casefold()}",
        "source": f"precomputed-{action.casefold()}",
        "channel": channel,
        "family": family,
        "status": "SUCCEEDED",
        "q_in": q_in,
        "q_src": q_src,
        "direction": direction,
        "observed_intervals": [{"start_us": 0, "end_us": 1_000_000}],
        "risk_atom_ids": [f"atom-{action.casefold()}"],
        "fact_tokens": [action.casefold()],
        "embedding": [0.0, 1.0] if action == "VLM" else None,
    }


def _accepted(adapter: PrecomputedEvidenceAdapter, raw: dict[str, Any]):
    action = str(raw["channel"])
    if action == "ACOUSTIC_EVENT":
        action = "AUDIO"
    return adapter.accept(action, raw, payload_hash(raw))


def _b4_inputs(evidence: float, reliability: float) -> tuple[MvpB2Output, MvpB6Output]:
    direction = evidence / reliability if reliability else 0.0
    modality = MvpModalityEvidence(
        channel="VLM",
        family="VISUAL",
        positive=max(evidence, 0.0),
        negative=max(-evidence, 0.0),
        quality=abs(evidence),
        direction=1.0 if evidence > 0 else (-1.0 if evidence < 0 else 0.0),
        observed_intervals=(MvpInterval(0, 1_000_000),),
    )
    b2 = MvpB2Output(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        slot="B2:final",
        positive=max(evidence, 0.0),
        negative=max(-evidence, 0.0),
        quality=reliability,
        direction=direction,
        conflict=0.0,
        e_local=evidence,
        u_local=1.0 - abs(evidence),
        modalities=(modality,),
        assessment_ids=("assessment",),
    )
    return b2, MvpB6Output(evidence, reliability, direction, 1.0 - abs(evidence), "TEST")


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


def _inference_root(summary: dict[str, Any]) -> Path:
    return Path(summary["output_attempt_root"]) / "inference"


def test_b3_records_decision_inputs_and_independent_tool_semantics() -> None:
    adapter = PrecomputedEvidenceAdapter()
    base_raw = _artifact("VLM", direction=0.6, q_in=0.95, q_src=1.0)
    ocr_raw = _artifact("OCR", direction=0.0, q_in=0.8, q_src=0.5)
    audio_raw = _artifact("AUDIO", direction=0.7, q_in=0.8, q_src=0.5)

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=MvpInterval(0, 1_000_000),
        base_results=(_accepted(adapter, base_raw),),
        action_artifacts={
            "OCR": (ocr_raw, payload_hash(ocr_raw)),
            "AUDIO": (audio_raw, payload_hash(audio_raw)),
        },
        adapter=adapter,
    )

    first = result.eligibility_audits[0]
    assert first.action == "OCR"
    assert first.coverage_threshold == 1.0
    assert first.observed_coverage == 1.0
    assert first.reliability_threshold == 1.0
    assert first.observed_reliability == pytest.approx(0.95)
    assert first.conflict == result.b2_outputs[0].conflict
    assert first.effective_reliability == pytest.approx(0.95)
    assert first.reasons == ("RELIABILITY_GAP",)
    assert first.selected is True
    assert first.decision == "SELECT"
    assert result.stop_reason == "BUDGET_EXHAUSTED"

    ocr_trace, audio_trace = result.tool_trace
    assert (ocr_trace.accepted, ocr_trace.informative, ocr_trace.contributed) == (True, False, False)
    assert (audio_trace.accepted, audio_trace.informative, audio_trace.contributed) == (True, True, True)
    assert ocr_trace.b2_delta is not None
    assert ocr_trace.b2_delta.delta_e_local == 0.0
    assert audio_trace.b2_delta is not None
    assert audio_trace.b2_delta.delta_e_local != 0.0


def test_b6_and_b4_diagnostics_expose_identity_fusion_and_intermediate_terms() -> None:
    b2, b6 = _b4_inputs(0.4, 0.5)
    case = MvpAdvisoryPayload("case-a", 0.9, 1.0, 1.0, ("atom-a",))

    detailed_b6 = fuse_b6_detailed(b2, (case,), memory_enabled=True)
    assert detailed_b6.output == fuse_b6(b2, (case,), memory_enabled=True)
    assert detailed_b6.audit.mode == "FUSION"
    assert detailed_b6.audit.source_case_ids == ("case-a",)
    assert detailed_b6.audit.memory_gate > 0.0
    assert detailed_b6.audit.output_evidence == detailed_b6.output.e_commit

    previous = MvpB4State.initial()
    detailed_b4 = compute_b4_detailed("video", "w0", 0, 1_000_000, b2, b6, previous)
    public_commit, public_state = compute_b4("video", "w0", 0, 1_000_000, b2, b6, previous)
    assert detailed_b4.commit == public_commit
    assert detailed_b4.state == public_state
    assert detailed_b4.audit.previous_version == 0
    assert detailed_b4.audit.previous_state == "NORMAL"
    assert detailed_b4.audit.tau_fast_us > 0.0
    assert detailed_b4.audit.tau_slow_us >= detailed_b4.audit.tau_fast_us
    assert 0.0 <= detailed_b4.audit.rho_fast <= detailed_b4.audit.rho_slow < 1.0
    assert 0.0 <= detailed_b4.audit.novelty <= 1.0
    assert 0.0 <= detailed_b4.audit.momentum_weight <= 1.0
    assert detailed_b4.audit.new_state == detailed_b4.commit.state
    assert detailed_b4.audit.score_interval == (detailed_b4.commit.lower, detailed_b4.commit.upper)
    assert detailed_b4.audit.transition_reason == detailed_b4.commit.transition_reason


def test_each_window_has_one_clean_hash_bound_diagnostic_and_index(tmp_path: Path) -> None:
    summary = run_synthetic_inference(
        attempt_id="mvp-diagnostics-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    inference = _inference_root(summary)
    diagnostics = sorted((inference / "diagnostics" / "windows").rglob("*.json"))
    predictions = tuple(summary["prediction_payload_hashes"])
    index_records = [json.loads(line) for line in (inference / "diagnostics" / "window_diagnostics.jsonl").read_text().splitlines()]

    assert len(diagnostics) == len(predictions) == len(index_records) == 8
    assert len({(item["video_id"], item["window_id"]) for item in index_records}) == 8
    manifest = json.loads((inference / "freezes" / "mvp_output_hash_manifest.json").read_bytes())
    entries = {entry["relative_ref"]: entry for entry in manifest["entries"]}
    for path, index in zip(diagnostics, index_records, strict=True):
        diagnostic = json.loads(path.read_bytes())
        relative = path.relative_to(inference).as_posix()
        assert FORBIDDEN_INFERENCE_KEYS.isdisjoint(_keys(diagnostic))
        assert index["relative_ref"] == relative
        assert index["sha256"] == entries[relative]["sha256"]
        window_ref = diagnostic["lineage"]["window_artifact_ref"]
        assert entries[window_ref]["sha256"] in entries[relative]["parent_payload_hashes"]
        assert diagnostic["prediction"]["payload_hash"] in BASELINE_PREDICTION_HASHES


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_missing_or_tampered_diagnostic_invalidates_freeze(tmp_path: Path, mutation: str) -> None:
    attempt_id = f"mvp-diagnostic-{mutation}-a"
    summary = run_synthetic_inference(
        attempt_id=attempt_id,
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    verify_frozen_attempt(tmp_path, attempt_id, inference_quiescent=True)
    diagnostic = next((_inference_root(summary) / "diagnostics" / "windows").rglob("*.json"))
    if mutation == "missing":
        diagnostic.unlink()
    else:
        diagnostic.write_bytes(diagnostic.read_bytes() + b" ")

    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        verify_frozen_attempt(tmp_path, attempt_id, inference_quiescent=True)


def test_instrumentation_preserves_predictions_and_is_deterministic(tmp_path: Path) -> None:
    left = run_synthetic_inference(
        attempt_id="mvp-diagnostic-repro-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )
    right = run_synthetic_inference(
        attempt_id="mvp-diagnostic-repro-b",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )

    assert tuple(left["prediction_payload_hashes"]) == BASELINE_PREDICTION_HASHES
    assert tuple(right["prediction_payload_hashes"]) == BASELINE_PREDICTION_HASHES
    left_root = _inference_root(left) / "diagnostics"
    right_root = _inference_root(right) / "diagnostics"
    assert (left_root / "window_diagnostics.jsonl").read_bytes() == (
        right_root / "window_diagnostics.jsonl"
    ).read_bytes()
    left_payloads = [path.read_bytes() for path in sorted((left_root / "windows").rglob("*.json"))]
    right_payloads = [path.read_bytes() for path in sorted((right_root / "windows").rglob("*.json"))]
    assert left_payloads == right_payloads


def test_evaluator_report_joins_frozen_stage_scores_after_inference(tmp_path: Path) -> None:
    result = run_outer_attempt(
        attempt_id="mvp-diagnostic-evaluator-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )

    attempt_root = tmp_path / "data" / "agentic_outputs" / "mvp" / result["attempt_id"]
    report = json.loads((attempt_root / result["diagnostic_report_ref"]).read_bytes())
    assert report["schema_version"] == "MVP_EVALUATOR_DIAGNOSTIC_V1"
    assert len(report["records"]) == 8
    first = report["records"][0]
    assert first["target"]["kind"] == "WINDOW_BINARY"
    assert set(first["stage_scores"]) == {"vlm_base", "b2_steps", "b2_final", "b6", "b4", "postprocess"}
    assert first["stage_scores"]["b4"]["score"] == first["stage_scores"]["postprocess"]["score"]

    inference_root = attempt_root / "inference"
    for path in inference_root.rglob("*"):
        if path.is_file():
            value = path.read_bytes().lower()
            assert not any(term in value for term in (b"annotation", b"ground_truth", b"metric_target"))
