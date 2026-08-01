from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..codec import payload_hash
from ..config import validate_inference_boundary
from ..contracts import (
    MvpEvidenceAtom,
    MvpEvidenceObservation,
    MvpFactContradiction,
    MvpInterval,
    MvpObservedTemporalFact,
    MvpPacketAssessment,
)
from ..failures import MvpFailure, recoverable
from ..math.numeric import require_signed_unit, require_unit
from ..memory.temporal import derive_allen_triples
from .packet_assessment import assess_observation


_ACTION_CHANNEL = {"VLM": "VLM", "OCR": "OCR", "AUDIO": "ACOUSTIC_EVENT", "EMBEDDING": "EMBEDDING"}
_ACTION_FAMILY = {"VLM": "VISUAL", "OCR": "VISUAL", "AUDIO": "AUDIO", "EMBEDDING": "VISUAL"}


@dataclass(frozen=True, slots=True)
class MvpAdapterResult:
    action: str
    accepted: bool
    observation: MvpEvidenceObservation | None
    assessment: MvpPacketAssessment | None
    failure: MvpFailure | None
    raw_payload_hash: str | None


class PrecomputedEvidenceAdapter:
    """Narrow adapter: frozen bytes-in, immutable MVP DTOs-out."""

    identity = "PRECOMPUTED_EVIDENCE_MVP_V0"

    def accept(
        self,
        action: str,
        raw: Mapping[str, Any] | None,
        expected_payload_hash: str | None,
    ) -> MvpAdapterResult:
        if action not in _ACTION_CHANNEL:
            raise ValueError("action is outside the frozen adapter registry")
        if raw is None or expected_payload_hash is None:
            return self._unavailable(action, "precomputed artifact is missing")
        validate_inference_boundary(raw)
        actual_hash = payload_hash(dict(raw))
        if actual_hash != expected_payload_hash:
            return self._unavailable(action, "precomputed artifact hash mismatch", actual_hash)
        if raw.get("status") != "SUCCEEDED":
            return self._unavailable(action, "precomputed tool result is unavailable", actual_hash)
        if raw.get("channel") != _ACTION_CHANNEL[action] or raw.get("family") != _ACTION_FAMILY[action]:
            return self._unavailable(action, "precomputed channel mapping is invalid", actual_hash)
        try:
            intervals = tuple(
                MvpInterval(int(item["start_us"]), int(item["end_us"]))
                for item in raw.get("observed_intervals", ())
            )
            if not intervals:
                raise ValueError("successful observation requires coverage")
            q_in = require_unit(float(raw["q_in"]), "q_in")
            q_src = require_unit(float(raw["q_src"]), "q_src")
            direction = require_signed_unit(float(raw["direction"]), "direction")
            embedding_raw = raw.get("embedding")
            embedding = None if embedding_raw is None else tuple(float(value) for value in embedding_raw)
            if raw.get("temporal_triples"):
                raise ValueError("precomputed temporal relations are forbidden without observed timestamps")
            temporal_facts = tuple(
                MvpObservedTemporalFact(
                    fact_id=str(item["fact_id"]),
                    interval=MvpInterval(int(item["start_us"]), int(item["end_us"])),
                )
                for item in raw.get("temporal_facts", ())
            )
            triples = derive_allen_triples(temporal_facts)
            atoms = tuple(
                MvpEvidenceAtom(
                    atom_id=str(item["atom_id"]),
                    source_family=str(item["source_family"]),
                    status=str(item["status"]),
                    role=str(item["role"]),
                    direction=float(item["direction"]),
                    validity_gate=int(item["validity_gate"]),
                    q_in=float(item["q_in"]),
                    q_src=float(item["q_src"]),
                    interval=MvpInterval(int(item["interval"]["start_us"]), int(item["interval"]["end_us"])),
                    fact_slot=None
                    if item.get("fact_slot") is None
                    else tuple(str(value) for value in item["fact_slot"]),
                    interpretation_trace=None
                    if item.get("interpretation_trace") is None
                    else str(item["interpretation_trace"]),
                    quality_policy=str(item.get("quality_policy", "MEASURED")),
                )
                for item in raw.get("atoms", ())
            )
            if any(atom.fact_slot is not None and len(atom.fact_slot) != 4 for atom in atoms):
                raise ValueError("fact slot arity")
            contradictions = tuple(
                MvpFactContradiction(
                    left_atom_id=str(item["left_atom_id"]),
                    right_atom_id=str(item["right_atom_id"]),
                    score=float(item["score"]),
                )
                for item in raw.get("fact_contradictions", ())
            )
            risk_atom_ids = tuple(str(value) for value in raw.get("risk_atom_ids", ()))
            if atoms:
                valid_risk_ids = {atom.atom_id for atom in atoms if atom.status == "VALID" and atom.role == "RISK"}
                if not set(risk_atom_ids).issubset(valid_risk_ids):
                    raise ValueError("risk atom IDs are not valid observed RISK atoms")
            observation = MvpEvidenceObservation(
                observation_id=str(raw["observation_id"]),
                source=str(raw["source"]),
                channel=str(raw["channel"]),
                family=str(raw["family"]),
                status="SUCCEEDED",
                q_in=q_in,
                q_src=q_src,
                direction=direction,
                observed_intervals=intervals,
                risk_atom_ids=risk_atom_ids,
                fact_tokens=tuple(str(value) for value in raw.get("fact_tokens", ())),
                embedding=embedding,
                temporal_triples=triples,
                atoms=atoms,
                fact_contradictions=contradictions,
                temporal_facts=temporal_facts,
            )
            assessment = assess_observation(observation)
        except (KeyError, TypeError, ValueError) as exc:
            return self._unavailable(action, "precomputed artifact parse failed", actual_hash)
        return MvpAdapterResult(action, True, observation, assessment, None, actual_hash)

    @staticmethod
    def _unavailable(action: str, message: str, raw_hash: str | None = None) -> MvpAdapterResult:
        failure = recoverable("MVP_TOOL_UNAVAILABLE", message)
        return MvpAdapterResult(action, False, None, None, failure, raw_hash)
