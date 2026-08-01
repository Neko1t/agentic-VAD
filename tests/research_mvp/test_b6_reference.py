from __future__ import annotations

import math

import pytest

from src.research_mvp.contracts import MvpAdvisoryPayload, MvpB2Output
from src.research_mvp.math.b6 import fuse_b6, identity_b6, memory_mass


def local_b2(*, quality: float, direction: float, conflict: float = 0.0) -> MvpB2Output:
    e_local = quality * (1.0 - conflict) * direction
    return MvpB2Output(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        slot="B2:final",
        positive=max(e_local, 0.0),
        negative=max(-e_local, 0.0),
        quality=quality,
        direction=direction,
        conflict=conflict,
        e_local=e_local,
        u_local=1.0 - abs(e_local),
        modalities=(),
        assessment_ids=(),
    )


def test_b6_empty_reference_is_fieldwise_identity() -> None:
    local = local_b2(quality=0.6, direction=0.5)

    output = fuse_b6(local, (), memory_enabled=True, empty_status="EMPTY_IDENTITY")

    assert output == identity_b6(local, "EMPTY_IDENTITY")
    assert output.e_commit == pytest.approx(0.3)
    assert output.reliability_commit == pytest.approx(0.6)
    assert output.direction_commit == pytest.approx(0.5)
    assert output.u_commit == pytest.approx(0.7)


def test_b6_rank_weighted_mass_uses_only_payload_fields() -> None:
    cases = (
        MvpAdvisoryPayload("case-b", reliability=0.9, consistency=1.0, direction=1.0, atom_ids=("b",)),
        MvpAdvisoryPayload("case-a", reliability=0.8, consistency=1.0, direction=-1.0, atom_ids=("a",)),
    )

    mass = memory_mass(cases)

    assert mass.weights == pytest.approx((2.0 / 3.0, 1.0 / 3.0))
    assert mass.positive == pytest.approx(0.6)
    assert mass.negative == pytest.approx(0.8 / 3.0)
    assert mass.evidence == pytest.approx(1.0 / 3.0)


def test_b6_fusion_is_finite_bounded_and_traceable() -> None:
    local = local_b2(quality=0.4, direction=0.1)
    cases = (MvpAdvisoryPayload("case-b", 0.9, 1.0, 1.0, ("b",)),)

    output = fuse_b6(local, cases, memory_enabled=True)

    assert output.memory_status == "FUSED"
    assert output.source_case_ids == ("case-b",)
    assert math.isfinite(output.e_commit)
    assert abs(output.e_commit) <= output.reliability_commit <= 1.0
    assert -1.0 <= output.direction_commit <= 1.0
    assert output.u_commit == pytest.approx(1.0 - abs(output.e_commit))
    assert output.e_commit != local.e_local


def test_b6_disabled_is_identity() -> None:
    local = local_b2(quality=0.4, direction=0.1)
    case = MvpAdvisoryPayload("case-b", 1.0, 1.0, 1.0, ())
    assert fuse_b6(local, (case,), memory_enabled=False) == identity_b6(local, "DISABLED_IDENTITY")
