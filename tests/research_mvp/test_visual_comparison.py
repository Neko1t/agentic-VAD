from __future__ import annotations

import json
import copy
import subprocess
import sys
from pathlib import Path

import pytest

from src.research_mvp.adapters.semantic_scores import precompute_semantic_scores
from src.research_mvp.artifacts.hashes import file_sha256
from src.research_mvp.evaluator.metrics import (
    DIRECT_B4_POSTPROCESS,
    evaluate_binary_metrics,
    project_video_predictions,
)
from src.research_mvp.visual_comparison import compare_visual_attempt
from src.research_mvp.failures import MvpFailure
from src.research_mvp.launcher import verify_frozen_attempt
from src.research_mvp.media import OFFLINE_PROTOCOL
from src.research_mvp.runtime.video_runner import run_precomputed_inference

from .test_real_asset_pipeline import FakeSemanticScoringBackend, _visual_bundle


@pytest.fixture
def visual_case(tmp_path: Path):
    bundle, _, _ = _visual_bundle(tmp_path)
    semantic = precompute_semantic_scores(
        input_manifest_path=bundle.input_manifest_path,
        output_root=tmp_path / "semantic",
        backend=FakeSemanticScoringBackend(),
    )
    attempt_id = "mvp-visual-comparison"
    run_precomputed_inference(
        attempt_id=attempt_id,
        project_root=tmp_path,
        input_manifest_path=bundle.input_manifest_path,
        memory_enabled=False,
        tool_policy="NONE",
        semantic_score_manifest_path=semantic.manifest_path,
        semantic_score_manifest_sha256=semantic.manifest_sha256,
    )
    target = tmp_path / "targets.json"
    target.write_text(
        json.dumps(
            {
                "dataset_id": "mvp-real-assets-test",
                "experiment_config_id": "I3",
                "frame_interval": 16,
                "manifest_type": "MVP_FRAME_TARGETS_V1",
                "normal_label": 0,
                "postprocess_identity": DIRECT_B4_POSTPROCESS,
                "temporal_protocol": OFFLINE_PROTOCOL,
                "videos": [
                    {"video_id": "mvp-video-real-reference", "frame_count": 32, "anomaly_intervals": []},
                    {
                        "video_id": "mvp-video-real-salient",
                        "frame_count": 32,
                        "anomaly_intervals": [{"start_frame": 16, "end_frame": 31}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return dict(
        project_root=tmp_path,
        attempt_id=attempt_id,
        input_manifest_path=bundle.input_manifest_path,
        semantic_score_manifest_path=semantic.manifest_path,
        semantic_score_manifest_sha256=semantic.manifest_sha256,
        target_manifest_path=target,
        output_root=tmp_path / "data/agentic_outputs/mvp/comparisons/visual-a",
    )


def test_visual_comparison_is_same_input_hash_bound_and_non_mutating(visual_case) -> None:
    args = visual_case
    before = verify_frozen_attempt(args["project_root"], args["attempt_id"], inference_quiescent=True)
    result = compare_visual_attempt(**args)
    after = verify_frozen_attempt(args["project_root"], args["attempt_id"], inference_quiescent=True)
    assert before["hash_inventory"] == after["hash_inventory"]
    assert result["status_code"] == "VISUAL_COMPARISON_COMPLETED"
    root = args["output_root"]
    report = json.loads((root / "comparison.json").read_bytes())
    assert set(report["arms"]) == {"V0", "V1", "V2"}
    assert report["frame_count"] == 64 and report["window_count"] == 4
    assert report["research_claim_status"] == "NO_RESEARCH_CLAIM"
    assert report["provenance"]["semantic_score_manifest_sha256"] == args["semantic_score_manifest_sha256"]
    for arm in report["arms"].values():
        assert arm["config"]["tool_policy"] == "NONE"
        assert arm["config"]["memory_enabled"] is False
        assert arm["per_video"]["mvp-video-real-reference"]["metrics"]["roc_auc"]["status"] == "METRIC_UNDEFINED"
    rows = [json.loads(line) for line in (root / "window_scores.jsonl").read_bytes().splitlines()]
    assert all(row["caption"] and row["llm_raw_response"] for row in rows)
    assert {r["V0"] for r in rows} == {0.1, 0.9}
    assert report["arms"]["V0"]["metrics"] == evaluate_binary_metrics((0,) * 48 + (1,) * 16, (0.1,) * 32 + (0.9,) * 32)
    assert "作者式" in (root / "report_zh.md").read_text(encoding="utf-8")
    receipt = json.loads((root / "receipt.json").read_bytes())
    assert all(file_sha256(root / row["relative_ref"]) == row["sha256"] for row in receipt["artifacts"])
    with pytest.raises(MvpFailure):
        compare_visual_attempt(**args)


@pytest.mark.parametrize("change", ["hash", "dataset", "frames", "protocol", "output"])
def test_visual_comparison_rejects_incompatible_inputs_before_publish(visual_case, change) -> None:
    args = dict(visual_case)
    if change == "hash":
        args["semantic_score_manifest_sha256"] = "0" * 64
    elif change == "output":
        args["output_root"] = args["project_root"] / "data/agentic_outputs/mvp" / args["attempt_id"] / "extra"
    else:
        target = json.loads(args["target_manifest_path"].read_bytes())
        if change == "dataset":
            target["dataset_id"] = "another-dataset"
        elif change == "frames":
            target["videos"][0]["frame_count"] = 33
        else:
            target["temporal_protocol"] = "ZS-Independent-Causal"
        args["target_manifest_path"].write_text(json.dumps(target), encoding="utf-8")
    with pytest.raises((ValueError, MvpFailure)):
        compare_visual_attempt(**args)
    assert not args["output_root"].exists()


def test_visual_comparison_cli_is_separate_and_emits_json(visual_case) -> None:
    args = visual_case
    command = [sys.executable, "-m", "src.research_mvp.cli", "compare-visual"]
    for key, value in args.items():
        flag = {
            "input_manifest_path": "input-manifest",
            "semantic_score_manifest_path": "semantic-score-manifest",
            "target_manifest_path": "target-manifest",
        }.get(key, key.replace("_", "-"))
        command.extend([f"--{flag}", str(value)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status_code"] == "VISUAL_COMPARISON_COMPLETED"


def test_visual_comparison_rejects_memory_or_tool_activity(visual_case) -> None:
    from src.research_mvp.evaluator.visual_comparison import build_visual_comparison

    args = visual_case
    verified = verify_frozen_attempt(args["project_root"], args["attempt_id"], inference_quiescent=True)
    root = verified["inference_root"]
    predictions = [
        json.loads(line) for path in (root / "predictions").glob("*.jsonl") for line in path.read_bytes().splitlines()
    ]
    diagnostics = [json.loads(path.read_bytes()) for path in (root / "diagnostics/windows").rglob("*.json")]
    semantic = json.loads(args["semantic_score_manifest_path"].read_bytes())["scores"]
    targets = json.loads(args["target_manifest_path"].read_bytes())
    for mode in ("memory", "tools"):
        altered = copy.deepcopy(diagnostics)
        if mode == "memory":
            altered[0]["b6"]["audit"]["mode"] = "IDENTITY_EMPTY"
        else:
            altered[0]["b3"]["attempted_actions"] = ["OCR"]
        with pytest.raises(ValueError, match="tools and Memory disabled"):
            build_visual_comparison(predictions, altered, semantic, targets)


def test_visual_comparison_smooths_within_each_video_before_tail_expansion() -> None:
    from src.research_mvp.evaluator.visual_comparison import build_visual_comparison
    from src.research_mvp.ids import window_semantic_id

    predictions, diagnostics, semantic, videos = [], [], [], []
    for video_id, values in (("mvp-video-a", (0.0, 0.9, 0.1)), ("mvp-video-b", (0.8, 0.1, 1.0))):
        videos.append(
            {"video_id": video_id, "frame_count": 33, "anomaly_intervals": [{"start_frame": 16, "end_frame": 31}]}
        )
        for ordinal, score in enumerate(values):
            base = {
                "video_id": video_id,
                "window_id": window_semantic_id(video_id, ordinal),
                "window_ordinal": ordinal,
            }
            predictions.append(
                {
                    **base,
                    "start_frame": ordinal * 16,
                    "end_frame": min(ordinal * 16 + 15, 32),
                    "frame_count": 33,
                    "frame_interval": 16,
                    "prediction": 0.5,
                }
            )
            semantic.append(
                {
                    **base,
                    "anomaly_score": score,
                    "caption_payload_hash": "a" * 64,
                    "parse_status": "PARSED",
                    "raw_response": str([score]),
                }
            )
            diagnostics.append(
                {
                    **base,
                    "prediction": {"score": 0.5},
                    "b3": {"attempted_actions": [], "tool_actions": []},
                    "b6": {"audit": {"mode": "IDENTITY_DISABLED"}},
                    "b4": {"audit": {"new_state": "NORMAL"}},
                    "b2": {"stages": [{"slot": "B2:final", "e_local": 0.0, "quality": 0.0}]},
                }
            )
    target = {
        "dataset_id": "test",
        "experiment_config_id": "I3",
        "frame_interval": 16,
        "manifest_type": "MVP_FRAME_TARGETS_V1",
        "normal_label": 0,
        "postprocess_identity": DIRECT_B4_POSTPROCESS,
        "temporal_protocol": OFFLINE_PROTOCOL,
        "videos": videos,
    }
    report, rows = build_visual_comparison(predictions, diagnostics, semantic, target)
    assert report["frame_count"] == 66 and rows[2]["window_frame_count"] == 1
    for video in videos:
        raw = [
            {**p, "prediction": s["anomaly_score"]}
            for p, s in zip(predictions, semantic)
            if p["video_id"] == video["video_id"]
        ]
        expected = project_video_predictions(raw, frame_count=33, frame_interval=16, gaussian_sigma=10.0)
        assert [r["V1"] for r in rows if r["video_id"] == video["video_id"]] == [expected[i] for i in (0, 16, 32)]
