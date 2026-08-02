from __future__ import annotations

import os
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from .failures import fatal
from .ids import validate_attempt_id


REFERENCE_PROFILE = "RESEARCH_MVP"
RESEARCH_CLAIM_STATUS = "NO_RESEARCH_CLAIM"
TOOL_POLICIES = {"ALL": ("OCR", "AUDIO"), "NONE": ()}
_POISON_TERMS = ("label", "annotation", "ground_truth", "ground truth", "metric_target", "metric target")


def _contains_poison(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.casefold()
        return any(term in lowered for term in _POISON_TERMS)
    if isinstance(value, Mapping):
        return any(_contains_poison(str(key)) or _contains_poison(item) for key, item in value.items())
    if is_dataclass(value) and not isinstance(value, type):
        return any(_contains_poison(field.name) or _contains_poison(getattr(value, field.name)) for field in fields(value))
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_poison(item) for item in value)
    return False


def validate_inference_boundary(*values: Any) -> None:
    if any(_contains_poison(value) for value in values):
        raise fatal("MVP_GROUND_TRUTH_POISON", "ground-truth capability is forbidden in inference")


def validate_inference_environment(environ: Mapping[str, str] | None = None) -> None:
    source = os.environ if environ is None else environ
    validate_inference_boundary(dict(source))


@dataclass(frozen=True, slots=True)
class MvpInferenceConfig:
    attempt_id: str
    memory_namespace_id: str
    output_root: Path
    memory_root: Path
    runtime_profile: str = REFERENCE_PROFILE
    video_workers: int = 1
    window_workers: int = 1
    device_policy: str = "PRECOMPUTED_CPU"
    batch_size: int = 1
    memory_capacity: int = 512
    retrieval_k: int = 5
    rrf_constant: int = 60
    optional_pass_1: bool = False
    resume: bool = False
    tool_policy: str = "ALL"

    def __post_init__(self) -> None:
        validate_attempt_id(self.attempt_id)
        if self.memory_namespace_id != self.attempt_id:
            raise ValueError("memory_namespace_id must equal attempt_id")
        if self.runtime_profile != REFERENCE_PROFILE:
            raise ValueError("unregistered MVP runtime profile")
        if self.video_workers != 1 or self.window_workers != 1 or self.batch_size != 1:
            raise ValueError("reference MVP execution is strictly sequential")
        if self.memory_capacity != 512 or self.retrieval_k != 5 or self.rrf_constant != 60:
            raise ValueError("reference MVP numeric profile is frozen")
        if self.optional_pass_1 or self.resume:
            raise ValueError("reference MVP forbids optional pass 1 and resume")
        if self.tool_policy not in TOOL_POLICIES:
            raise ValueError("tool_policy is outside the frozen MVP registry")
        validate_inference_boundary(self)

    @classmethod
    def reference(
        cls,
        attempt_id: str,
        project_root: Path | None = None,
        *,
        tool_policy: str = "ALL",
    ) -> "MvpInferenceConfig":
        attempt_id = validate_attempt_id(attempt_id)
        base = project_root if project_root is not None else Path(".")
        return cls(
            attempt_id=attempt_id,
            memory_namespace_id=attempt_id,
            output_root=base / "data" / "agentic_outputs" / "mvp" / attempt_id,
            memory_root=base / "data" / "agentic_memory" / "mvp" / attempt_id,
            tool_policy=tool_policy,
        )

    @property
    def tool_action_order(self) -> tuple[str, ...]:
        return TOOL_POLICIES[self.tool_policy]

    @property
    def research_claim_status(self) -> str:
        return RESEARCH_CLAIM_STATUS
