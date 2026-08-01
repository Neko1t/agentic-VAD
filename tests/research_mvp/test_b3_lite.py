from __future__ import annotations

from dataclasses import fields

import pytest

from src.research_mvp.codec import payload_hash
from src.research_mvp.contracts import MvpInterval
from src.research_mvp.evidence.adapters import PrecomputedEvidenceAdapter
from src.research_mvp.evidence.b3_lite import run_b3_lite


WINDOW = MvpInterval(0, 1_000_000)


def artifact(
    action: str,
    *,
    status: str = "SUCCEEDED",
    direction: float = 0.5,
    q_in: float = 0.8,
    q_src: float = 0.5,
    start_us: int = 0,
    end_us: int = 1_000_000,
    atoms: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    channel = {"VLM": "VLM", "OCR": "OCR", "AUDIO": "ACOUSTIC_EVENT"}[action]
    family = "AUDIO" if action == "AUDIO" else "VISUAL"
    return {
        "observation_id": f"obs-{action.casefold()}",
        "source": f"precomputed-{action.casefold()}",
        "channel": channel,
        "family": family,
        "status": status,
        "q_in": q_in,
        "q_src": q_src,
        "direction": direction,
        "observed_intervals": [{"start_us": start_us, "end_us": end_us}],
        "risk_atom_ids": [f"atom-{action.casefold()}"],
        "fact_tokens": [action.casefold()],
        "embedding": [0.0, 1.0] if action == "VLM" else None,
        "temporal_facts": [
            {"fact_id": action.casefold(), "start_us": start_us, "end_us": start_us + (end_us - start_us) // 3},
            {"fact_id": "end", "start_us": start_us + 2 * (end_us - start_us) // 3, "end_us": end_us},
        ],
        **({"atoms": atoms} if atoms is not None else {}),
    }


def accepted(adapter: PrecomputedEvidenceAdapter, action: str):
    raw = artifact(action)
    return adapter.accept(action, raw, payload_hash(raw))


def test_one_accepted_observation_produces_exactly_one_assessment() -> None:
    result = accepted(PrecomputedEvidenceAdapter(), "VLM")

    assert result.accepted is True
    assert result.observation is not None
    assert result.assessment is not None
    assert result.assessment.observation_id == result.observation.observation_id
    assert result.assessment.reliability == pytest.approx(0.4)


def test_adapter_carries_e0_atoms_into_the_single_packet_assessment() -> None:
    raw = artifact(
        "VLM",
        atoms=[
            {
                "atom_id": "atom-vlm",
                "direction": 0.5,
                "fact_slot": ["Person", "Carry", "Object", "Relation"],
                "interval": {"start_us": 0, "end_us": 1_000_000},
                "q_in": 0.8,
                "q_src": 0.5,
                "role": "RISK",
                "source_family": "VISUAL",
                "status": "VALID",
                "validity_gate": 1,
            }
        ],
    )

    result = PrecomputedEvidenceAdapter().accept("VLM", raw, payload_hash(raw))

    assert result.accepted is True
    assert result.observation is not None
    assert result.assessment is not None
    assert tuple(atom.atom_id for atom in result.observation.atoms) == ("atom-vlm",)
    assert result.assessment.atoms == result.observation.atoms


@pytest.mark.parametrize(
    ("raw", "expected_hash"),
    [
        (None, None),
        (artifact("OCR", status="FAILED"), None),
        (artifact("OCR"), "0" * 64),
    ],
)
def test_missing_failed_or_hash_mismatch_produces_no_vote(raw, expected_hash) -> None:
    if raw is not None and expected_hash is None:
        expected_hash = payload_hash(raw)
    result = PrecomputedEvidenceAdapter().accept("OCR", raw, expected_hash)

    assert result.accepted is False
    assert result.observation is None
    assert result.assessment is None
    assert result.failure is not None
    assert "normal_score" not in {field.name for field in fields(result)}


def test_b3_lite_uses_fixed_action_order_and_closed_slots() -> None:
    adapter = PrecomputedEvidenceAdapter()
    base = accepted(adapter, "VLM")
    ocr = artifact("OCR")
    audio = artifact("AUDIO")

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts={
            "AUDIO": (audio, payload_hash(audio)),
            "OCR": (ocr, payload_hash(ocr)),
        },
        adapter=adapter,
    )

    assert result.attempted_actions == ("OCR", "AUDIO")
    assert result.accepted_actions == ("OCR", "AUDIO")
    assert tuple(output.slot for output in result.b2_outputs) == (
        "B2:base",
        "B2:step-000",
        "B2:step-001",
        "B2:final",
    )
    assert result.final_b2.slot == "B2:final"
    assert len(result.attempted_actions) == len(set(result.attempted_actions)) == 2
    assert len(result.final_b2.assessment_ids) == 3


def test_failed_action_has_no_pseudo_step_but_next_action_can_succeed() -> None:
    adapter = PrecomputedEvidenceAdapter()
    base = accepted(adapter, "VLM")
    failed_ocr = artifact("OCR", status="FAILED")
    audio = artifact("AUDIO")

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts={
            "OCR": (failed_ocr, payload_hash(failed_ocr)),
            "AUDIO": (audio, payload_hash(audio)),
        },
        adapter=adapter,
    )

    assert result.attempted_actions == ("OCR", "AUDIO")
    assert result.accepted_actions == ("AUDIO",)
    assert tuple(output.slot for output in result.b2_outputs) == (
        "B2:base",
        "B2:step-001",
        "B2:final",
    )
    assert result.final_b2.assessment_ids == ("assessment-obs-audio", "assessment-obs-vlm")


def test_full_coverage_and_reliability_close_optional_action_gaps() -> None:
    adapter = PrecomputedEvidenceAdapter()
    raw_base = artifact("VLM", q_in=1.0, q_src=1.0)
    base = adapter.accept("VLM", raw_base, payload_hash(raw_base))
    artifacts = {action: (raw := artifact(action), payload_hash(raw)) for action in ("OCR", "AUDIO")}

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts=artifacts,
        adapter=adapter,
    )

    assert result.attempted_actions == ()
    assert result.stop_reason == "GAPS_CLOSED"
    assert tuple(output.slot for output in result.b2_outputs) == ("B2:base", "B2:final")


def test_partial_observed_coverage_makes_missing_actions_eligible() -> None:
    adapter = PrecomputedEvidenceAdapter()
    raw_base = artifact("VLM", q_in=1.0, q_src=1.0, end_us=500_000)
    base = adapter.accept("VLM", raw_base, payload_hash(raw_base))
    artifacts = {action: (raw := artifact(action), payload_hash(raw)) for action in ("OCR", "AUDIO")}

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts=artifacts,
        adapter=adapter,
    )

    assert result.attempted_actions == ("OCR",)
    assert result.tool_trace[0].eligibility_reasons == ("OBSERVED_COVERAGE_GAP",)


def test_explicit_missing_capability_is_selected_even_without_other_gap() -> None:
    adapter = PrecomputedEvidenceAdapter()
    raw_base = artifact("VLM", q_in=1.0, q_src=1.0)
    base = adapter.accept("VLM", raw_base, payload_hash(raw_base))
    ocr = artifact("OCR", q_in=1.0, q_src=1.0)
    audio = artifact("AUDIO")

    result = run_b3_lite(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts={"OCR": (ocr, payload_hash(ocr)), "AUDIO": (audio, payload_hash(audio))},
        adapter=adapter,
        required_actions=("OCR",),
    )

    assert result.attempted_actions == ("OCR",)
    assert result.tool_trace[0].eligibility_reasons == ("MISSING_CAPABILITY",)


def test_same_frozen_inputs_are_deterministic() -> None:
    adapter = PrecomputedEvidenceAdapter()
    base = accepted(adapter, "VLM")
    artifacts = {action: (raw := artifact(action), payload_hash(raw)) for action in ("OCR", "AUDIO")}
    kwargs = dict(
        video_id="video",
        window_id="window",
        window_ordinal=0,
        window=WINDOW,
        base_results=(base,),
        action_artifacts=artifacts,
        adapter=adapter,
    )
    assert run_b3_lite(**kwargs) == run_b3_lite(**kwargs)
