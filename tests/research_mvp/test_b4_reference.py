from __future__ import annotations

import math

import pytest

from src.research_mvp.contracts import MvpB2Output, MvpB6Output, MvpInterval, MvpModalityEvidence
from src.research_mvp.math.b4 import B4Committer, MvpB4State, compute_b4


def inputs(evidence: float, reliability: float) -> tuple[MvpB2Output, MvpB6Output]:
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
    b6 = MvpB6Output(evidence, reliability, direction, 1.0 - abs(evidence), "TEST")
    return b2, b6


def test_b4_first_valid_then_missing_decays_without_negative_injection() -> None:
    b2, b6 = inputs(0.6, 0.6)
    first, state = compute_b4("video", "w0", 0, 1_000_000, b2, b6, MvpB4State.initial())
    missing_b2, missing_b6 = inputs(0.0, 0.0)
    second, _ = compute_b4("video", "w1", 1, 1_000_000, missing_b2, missing_b6, state)

    assert first.fast == pytest.approx(0.6)
    assert first.slow == pytest.approx(0.6)
    assert 0.0 <= second.fast < first.fast
    assert 0.0 <= second.slow < first.slow
    assert second.state != "NORMAL" if first.state == "ABNORMAL" else True


def test_hysteresis_changes_only_discrete_state_not_continuous_z() -> None:
    b2, b6 = inputs(0.2, 0.2)
    normal = MvpB4State.initial(state="NORMAL")
    abnormal = MvpB4State.initial(state="ABNORMAL")

    normal_commit, _ = compute_b4("video", "w0", 0, 1_000_000, b2, b6, normal)
    abnormal_commit, _ = compute_b4("video", "w0", 0, 1_000_000, b2, b6, abnormal)

    assert normal_commit.z == abnormal_commit.z
    assert normal_commit.fast == abnormal_commit.fast
    assert normal_commit.slow == abnormal_commit.slow
    assert normal_commit.momentum == abnormal_commit.momentum
    assert normal_commit.state != abnormal_commit.state


def test_exactly_once_committer_rejects_duplicate_window() -> None:
    b2, b6 = inputs(0.9, 0.9)
    committer = B4Committer(MvpB4State.initial())

    commit = committer.commit("video", "w0", 0, 1_000_000, b2, b6)

    assert commit.version_after == 1
    with pytest.raises(ValueError, match="exactly once"):
        committer.commit("video", "w0", 0, 1_000_000, b2, b6)


def test_b4_outputs_are_finite_and_bounded() -> None:
    b2, b6 = inputs(0.9, 0.9)
    commit, _ = compute_b4("video", "w0", 0, 1_000_000, b2, b6, MvpB4State.initial())
    for value in (commit.fast, commit.slow, commit.momentum):
        assert math.isfinite(value)
        assert -1.0 <= value <= 1.0
    for value in (commit.z, commit.uncertainty, commit.lower, commit.upper):
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0


def test_math_modules_have_no_external_side_effect_imports() -> None:
    import ast
    from pathlib import Path

    math_root = Path(__file__).resolve().parents[2] / "src" / "research_mvp" / "math"
    forbidden = {"os", "pathlib", "socket", "sqlite3", "subprocess", "time"}
    forbidden_calls = {"open", "getenv"}
    for path in math_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert forbidden.isdisjoint(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
