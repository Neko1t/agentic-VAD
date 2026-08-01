from __future__ import annotations

import math

import pytest

from src.research_mvp.contracts import (
    MvpEvidenceAtom,
    MvpFactContradiction,
    MvpInterval,
    MvpPacketAssessment,
)
from src.research_mvp.math.b2 import build_b2_output


WINDOW = MvpInterval(0, 1_000_000)


def assessment(
    identifier: str,
    *,
    reliability: float,
    direction: float,
    channel: str = "VLM",
    family: str = "VISUAL",
    start_us: int = 0,
    end_us: int = 1_000_000,
    atoms: tuple[MvpEvidenceAtom, ...] = (),
) -> MvpPacketAssessment:
    return MvpPacketAssessment(
        assessment_id=identifier,
        observation_id=f"obs-{identifier}",
        channel=channel,
        family=family,
        reliability=reliability,
        direction=direction,
        observed_intervals=(MvpInterval(start_us, end_us),),
        risk_atom_ids=tuple(atom.atom_id for atom in atoms) or (f"atom-{identifier}",),
        atoms=atoms,
    )


def atom(
    identifier: str,
    *,
    family: str,
    direction: float,
    start_us: int,
    end_us: int,
    q_in: float,
    q_src: float,
    role: str = "RISK",
    status: str = "VALID",
    fact_slot: tuple[str, str, str, str] | None = ("person", "carry", "object", "relation"),
    interpretation_trace: str | None = None,
) -> MvpEvidenceAtom:
    return MvpEvidenceAtom(
        atom_id=identifier,
        source_family=family,
        status=status,
        role=role,
        direction=direction,
        validity_gate=1 if status == "VALID" else 0,
        q_in=q_in,
        q_src=q_src,
        interval=MvpInterval(start_us, end_us),
        fact_slot=fact_slot,
        interpretation_trace=interpretation_trace,
    )


def test_b2_reference_duplicate_uses_max_envelope() -> None:
    packet = assessment("one", reliability=0.8, direction=0.5)

    once = build_b2_output("video", "window", 0, WINDOW, (packet,), slot="B2:final")
    duplicated = build_b2_output("video", "window", 0, WINDOW, (packet, packet), slot="B2:final")

    assert once == duplicated
    assert once.positive == pytest.approx(0.4)
    assert once.negative == 0.0
    assert once.quality == pytest.approx(0.4)
    assert once.direction == pytest.approx(1.0)
    assert once.e_local == pytest.approx(0.4)
    assert once.u_local == pytest.approx(0.6)


def test_b2_overlap_and_family_fusion_are_bounded() -> None:
    packets = (
        assessment("visual-risk", reliability=0.8, direction=1.0, end_us=700_000),
        assessment("visual-counter", reliability=0.5, direction=-1.0, start_us=300_000),
        assessment(
            "audio-risk",
            reliability=0.6,
            direction=1.0,
            channel="ACOUSTIC_EVENT",
            family="AUDIO",
        ),
    )

    output = build_b2_output("video", "window", 0, WINDOW, packets, slot="B2:final")

    for value in (
        output.positive,
        output.negative,
        output.quality,
        output.conflict,
        output.u_local,
    ):
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0
    assert -1.0 <= output.direction <= 1.0
    assert -1.0 <= output.e_local <= 1.0
    assert output.e_local == pytest.approx(output.quality * (1.0 - output.conflict) * output.direction)
    assert output.u_local == pytest.approx(1.0 - abs(output.e_local))


def test_b2_e0_rejects_context_vote_and_untraced_negative_atom() -> None:
    context_vote = atom(
        "atom-context",
        family="VISUAL",
        role="CONTEXT",
        direction=0.1,
        start_us=0,
        end_us=1_000_000,
        q_in=1.0,
        q_src=1.0,
    )
    with pytest.raises(ValueError, match="CONTEXT"):
        build_b2_output(
            "video",
            "window",
            0,
            WINDOW,
            (assessment("context", reliability=1.0, direction=0.0, atoms=(context_vote,)),),
            slot="B2:final",
        )

    negative = atom(
        "atom-negative",
        family="VISUAL",
        direction=-1.0,
        start_us=0,
        end_us=1_000_000,
        q_in=1.0,
        q_src=1.0,
    )
    with pytest.raises(ValueError, match="interpretation trace"):
        build_b2_output(
            "video",
            "window",
            0,
            WINDOW,
            (assessment("negative", reliability=1.0, direction=-1.0, atoms=(negative,)),),
            slot="B2:final",
        )


def test_b2_e3_computes_max_residual_fact_conflict_from_valid_atoms() -> None:
    visual_atom = atom(
        "atom-visual",
        family="VISUAL",
        direction=1.0,
        start_us=0,
        end_us=1_000_000,
        q_in=0.8,
        q_src=1.0,
    )
    audio_atom = atom(
        "atom-audio",
        family="AUDIO",
        direction=1.0,
        start_us=500_000,
        end_us=1_000_000,
        q_in=0.5,
        q_src=1.0,
    )
    packets = (
        assessment("visual", reliability=0.8, direction=1.0, atoms=(visual_atom,)),
        assessment(
            "audio",
            reliability=0.5,
            direction=1.0,
            channel="ACOUSTIC_EVENT",
            family="AUDIO",
            atoms=(audio_atom,),
        ),
    )
    contradictions = (
        MvpFactContradiction("atom-audio", "atom-visual", 0.75),
        MvpFactContradiction("atom-visual", "atom-audio", 0.75),
    )

    output = build_b2_output(
        "video",
        "window",
        0,
        WINDOW,
        packets,
        slot="B2:final",
        fact_contradictions=contradictions,
    )

    assert output.direction_conflict == 0.0
    assert output.fact_conflict == pytest.approx(0.375)
    assert output.conflict == pytest.approx(0.375)
    assert output.e_local == pytest.approx(0.9 * (1.0 - 0.375))
    assert output.fact_conflict_pairs == (("atom-audio", "atom-visual", 0.375),)
    assert output.supporting_atom_ids == ("atom-audio", "atom-visual")
    assert output.counter_atom_ids == ()


def test_b2_e3_does_not_double_count_directional_opposition() -> None:
    visual_atom = atom(
        "atom-positive",
        family="VISUAL",
        direction=1.0,
        start_us=0,
        end_us=1_000_000,
        q_in=1.0,
        q_src=1.0,
    )
    audio_atom = atom(
        "atom-negative",
        family="AUDIO",
        direction=-1.0,
        start_us=0,
        end_us=1_000_000,
        q_in=1.0,
        q_src=1.0,
        interpretation_trace="directly refutes the same suspicious event",
    )
    packets = (
        assessment("positive", reliability=1.0, direction=1.0, atoms=(visual_atom,)),
        assessment(
            "negative",
            reliability=1.0,
            direction=-1.0,
            channel="ACOUSTIC_EVENT",
            family="AUDIO",
            atoms=(audio_atom,),
        ),
    )

    output = build_b2_output(
        "video",
        "window",
        0,
        WINDOW,
        packets,
        slot="B2:final",
        fact_contradictions=(MvpFactContradiction("atom-positive", "atom-negative", 1.0),),
    )

    assert output.direction_conflict == 1.0
    assert output.fact_conflict == 0.0
    assert output.fact_conflict_pairs == ()
    assert output.e_local == 0.0


@pytest.mark.parametrize("slot", ["bad", "B2:base:extra", "B2:step-xyz"])
def test_b2_rejects_open_ended_slot_names(slot: str) -> None:
    with pytest.raises(ValueError):
        build_b2_output("video", "window", 0, WINDOW, (), slot=slot)
