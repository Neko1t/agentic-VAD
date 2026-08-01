from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from src.research_mvp.evaluator.metrics import evaluate_binary_metrics
from src.research_mvp.evaluator.resolver import MvpEvaluatorResolver
from src.research_mvp.failures import MvpFailure
from src.research_mvp.launcher import run_outer_attempt, verify_frozen_attempt


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"


def test_metrics_are_finite_for_two_classes_and_undefined_for_single_class() -> None:
    defined = evaluate_binary_metrics((0, 0, 1, 1), (0.1, 0.2, 0.8, 0.9))
    undefined = evaluate_binary_metrics((1, 1, 1), (0.1, 0.2, 0.3))

    assert defined["roc_auc"]["status"] == "DEFINED"
    assert defined["pr_auc"]["status"] == "DEFINED"
    assert math.isfinite(defined["roc_auc"]["value"])
    assert math.isfinite(defined["pr_auc"]["value"])
    assert undefined["roc_auc"] == {"reason": "single_class", "status": "METRIC_UNDEFINED"}
    assert undefined["pr_auc"] == {"reason": "single_class", "status": "METRIC_UNDEFINED"}


def test_pr_auc_uses_precision_recall_curve_trapezoid_not_average_precision() -> None:
    metrics = evaluate_binary_metrics((1, 0, 1, 0), (0.9, 0.8, 0.7, 0.1))

    assert metrics["roc_auc"] == {"status": "DEFINED", "value": pytest.approx(0.75)}
    assert metrics["pr_auc"] == {"status": "DEFINED", "value": pytest.approx(0.7916666666666666)}
    assert metrics["pr_auc"]["value"] != pytest.approx(0.8333333333333333)


def test_incomplete_freeze_and_non_quiescent_inference_block_evaluator(tmp_path: Path) -> None:
    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        verify_frozen_attempt(tmp_path, "missing-attempt", inference_quiescent=True)
    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        verify_frozen_attempt(tmp_path, "missing-attempt", inference_quiescent=False)
    assert not (tmp_path / "data" / "agentic_outputs" / "mvp" / "missing-attempt" / "evaluation").exists()


def test_evaluator_resolver_is_exact_allowlist_and_default_deny(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    allowed = root / "inference" / "predictions" / "a.jsonl"
    allowed.parent.mkdir(parents=True)
    allowed.write_bytes(b"safe")
    resolver = MvpEvaluatorResolver(root, (("inference/predictions/a.jsonl", 4, "8b3369944dd2a3fab39e32d1aeb1f763946a458ae3e6368a46432adc8f3a0860"),))

    assert resolver.read("inference/predictions/a.jsonl") == b"safe"
    with pytest.raises(MvpFailure):
        resolver.read("inference/predictions/other.jsonl")
    with pytest.raises(MvpFailure):
        resolver.read("../memory_snapshot.json")


def test_outer_launcher_uses_distinct_process_and_preserves_inference_memory_hashes(tmp_path: Path) -> None:
    result = run_outer_attempt(
        attempt_id="mvp-isolation-a",
        project_root=tmp_path,
        fixture_path=FIXTURE,
        memory_enabled=True,
    )

    assert result["inference_process_exit_code"] == 0
    assert result["evaluator_process_exit_code"] == 0
    assert result["inference_process_id"] != result["evaluator_process_id"]
    assert result["evaluator_started_after_inference_exit"] is True
    assert result["inference_memory_hashes_unchanged"] is True
    assert result["research_claim_status"] == "NO_RESEARCH_CLAIM"
    assert result["runtime_profile"] == "RESEARCH_MVP"
    serialized = repr(result).casefold()
    assert "annotation" not in serialized
    assert "ground_truth" not in serialized
    assert "metric_intermediate" not in serialized
    assert "traceback" not in serialized

    inference_root = tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-isolation-a" / "inference"
    inference_bytes = b"\n".join(path.read_bytes().lower() for path in inference_root.rglob("*") if path.is_file())
    assert b"annotation" not in inference_bytes
    assert b"ground_truth" not in inference_bytes
    assert b"metric_target" not in inference_bytes


def test_inference_and_evaluator_modules_have_no_cross_imports() -> None:
    source = REPO_ROOT / "src" / "research_mvp"
    for path in (source / "runtime").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any("evaluator" in module for module in imports)
    for path in (source / "evaluator").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any("runtime" in module for module in imports)
