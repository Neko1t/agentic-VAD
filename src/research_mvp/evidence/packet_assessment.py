from __future__ import annotations

from ..contracts import MvpEvidenceObservation, MvpPacketAssessment
from ..math.numeric import multiply, require_signed_unit, require_unit


def assess_observation(observation: MvpEvidenceObservation) -> MvpPacketAssessment:
    if observation.status != "SUCCEEDED":
        raise ValueError("only accepted successful observations can be assessed")
    reliability = require_unit(multiply(observation.q_in, observation.q_src), "packet reliability")
    direction = require_signed_unit(observation.direction, "packet direction")
    return MvpPacketAssessment(
        assessment_id=f"assessment-{observation.observation_id}",
        observation_id=observation.observation_id,
        channel=observation.channel,
        family=observation.family,
        reliability=reliability,
        direction=direction,
        observed_intervals=observation.observed_intervals,
        risk_atom_ids=observation.risk_atom_ids,
        atoms=observation.atoms,
    )
