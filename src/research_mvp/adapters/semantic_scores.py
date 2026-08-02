from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .. import RESEARCH_CLAIM_STATUS, RUNTIME_PROFILE
from ..artifacts.hashes import file_sha256
from ..artifacts.publisher import MvpImmutablePublisher
from ..artifacts.resolver import resolve_relative, validate_path_identity
from ..codec import dumps, loads, payload_hash
from ..config import validate_inference_boundary
from ..failures import MvpFailure, fatal
from .real_assets import load_precomputed_input


SEMANTIC_SCORE_MANIFEST_TYPE = "MVP_SEMANTIC_SCORE_MANIFEST_V1"
SEMANTIC_SCORER_IDENTITY = "TRANSFORMERS_LLM_ANOMALY_SCORER_V1"
MAPPING_IDENTITY = "CENTERED_LINEAR_SCORE_TO_B2_V1"
ORIGINAL_CONTEXT_PROMPT = (
    "How would you rate the scene described on a scale from 0 to 1, with 0 representing a standard scene "
    "and 1 denoting a scene with suspicious activities or potentially criminal activities?"
)
ORIGINAL_FORMAT_PROMPT = (
    "Please provide the response in the form of a Python list and respond with only one number in the "
    "provided list below [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] without any textual "
    "explanation. It should begin with '[' and end with  ']'."
)
SAMPLING_CONFIG = {
    "batch_size": 32,
    "max_new_tokens": 16,
    "seed": 1,
    "temperature": 0.6,
    "top_p": 0.9,
}
ATTENTION_IMPLEMENTATION = "eager"

_SCORE = re.compile(r"\[(\d+(?:\.\d+)?)\]")
_MANIFEST_FIELDS = {
    "adapter_identity",
    "backend_identity",
    "context_prompt",
    "format_prompt",
    "input_manifest_sha256",
    "manifest_type",
    "mapping_identity",
    "model_provenance",
    "research_claim_status",
    "runtime_profile",
    "sampling",
    "score_count",
    "scores",
    "source_bundle_manifest_sha256",
}
_SCORE_FIELDS = {
    "anomaly_score",
    "caption_payload_hash",
    "parse_status",
    "raw_response",
    "source_vlm_payload_hash",
    "video_id",
    "window_id",
    "window_ordinal",
}


class MvpSemanticScoringBackend(Protocol):
    identity: str
    provenance: Mapping[str, Any]

    def score(self, captions: tuple[str, ...]) -> tuple[str, ...]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MvpSemanticScoreReceipt:
    manifest_path: Path
    manifest_sha256: str
    score_count: int
    status_code: str = "SEMANTIC_SCORES_FROZEN"


def _safe_failure(message: str, exc: Exception | None = None) -> MvpFailure:
    failure = fatal("MVP_FREEZE_INVALID", message)
    if exc is not None:
        failure.__cause__ = exc
    return failure


def _parse_score(response: str) -> float | None:
    match = _SCORE.search(response)
    if match is None:
        return None
    value = float(match.group(1))
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _interpolate(scores: tuple[float | None, ...]) -> tuple[float, ...]:
    valid = tuple((index, score) for index, score in enumerate(scores) if score is not None)
    if not valid:
        raise fatal("ASSET_NOT_RUN", "LLM produced no valid score for a video")
    output: list[float] = []
    for index, score in enumerate(scores):
        if score is not None:
            output.append(score)
            continue
        left = next(((position, value) for position, value in reversed(valid) if position < index), None)
        right = next(((position, value) for position, value in valid if position > index), None)
        if left is None:
            output.append(float(right[1]))  # type: ignore[index]
        elif right is None:
            output.append(float(left[1]))
        else:
            ratio = (index - left[0]) / (right[0] - left[0])
            output.append(float(left[1] + ratio * (right[1] - left[1])))
    return tuple(output)


def _caption_inputs(
    input_manifest_path: Path,
    fixture: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    by_id = {
        str(record["artifact_id"]): record
        for record in bundle.get("raw_output_artifacts", ())
        if isinstance(record, Mapping)
    }
    bundle_root = input_manifest_path.parent
    inputs: list[dict[str, Any]] = []
    for video in fixture["videos"]:
        video_id = str(video["video_id"])
        for window in video["windows"]:
            window_id = str(window["window_id"])
            record = by_id.get(f"raw:{video_id}/{window_id}:caption")
            if not isinstance(record, Mapping) or record.get("action") != "CAPTION":
                raise fatal("MVP_FREEZE_INVALID", "caption artifact registry is incomplete")
            path = resolve_relative(bundle_root, str(record["relative_ref"]))
            if (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_size != int(record["byte_length"])
                or file_sha256(path) != str(record["sha256"])
                or record["sha256"] != record["payload_hash"]
            ):
                raise fatal("MVP_FREEZE_INVALID", "caption artifact binding is invalid")
            try:
                raw = loads(path.read_bytes())
                caption = str(raw["text"]).strip()
            except Exception as exc:
                raise _safe_failure("caption artifact is unreadable", exc) from exc
            if not caption:
                raise fatal("ASSET_NOT_RUN", "caption artifact is empty")
            inputs.append(
                {
                    "caption": caption,
                    "caption_payload_hash": str(record["payload_hash"]),
                    "source_vlm_payload_hash": str(window["evidence_artifacts"]["VLM"]["payload_hash"]),
                    "video_id": video_id,
                    "window_id": window_id,
                    "window_ordinal": int(window["ordinal"]),
                }
            )
    return tuple(inputs)


def semantic_score_to_evidence(raw: Mapping[str, Any], score: float) -> dict[str, Any]:
    score = float(score)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("semantic anomaly score must be finite in [0,1]")
    if raw.get("channel") != "VLM" or raw.get("family") != "VISUAL" or raw.get("status") != "SUCCEEDED":
        raise ValueError("semantic mapping requires accepted VLM-shaped evidence")
    direction = -1.0 if score < 0.5 else 1.0 if score > 0.5 else 0.0
    quality = abs(2.0 * score - 1.0)
    intervals = raw.get("observed_intervals")
    if not isinstance(intervals, (list, tuple)) or not intervals:
        raise ValueError("semantic mapping requires observed coverage")
    observation_id = str(raw["observation_id"])
    atom_id = f"{observation_id.removeprefix('obs-')}-semantic-risk"
    atoms: list[dict[str, Any]] = []
    risk_atom_ids: list[str] = []
    if direction != 0.0:
        risk_atom_ids.append(atom_id)
        atoms.append(
            {
                "atom_id": atom_id,
                "direction": direction,
                "fact_slot": ["scene", "risk", "window", "llm-semantic"],
                "interpretation_trace": "LLM semantic score is below the neutral midpoint"
                if direction < 0.0
                else None,
                "interval": dict(intervals[0]),
                "q_in": quality,
                "q_src": 1.0,
                "quality_policy": "MEASURED",
                "role": "RISK",
                "source_family": "VISUAL",
                "status": "VALID",
                "validity_gate": 1,
            }
        )
    mapped = dict(raw)
    mapped.pop("smoke_cues", None)
    mapped.pop("smoke_mapper_identity", None)
    mapped.update(
        {
            "atoms": atoms,
            "direction": direction,
            "q_in": quality,
            "q_src": 1.0,
            "risk_atom_ids": risk_atom_ids,
            "semantic_anomaly_score": score,
            "semantic_mapping_identity": MAPPING_IDENTITY,
            "source": "llm-semantic-score-precomputed",
        }
    )
    validate_inference_boundary(mapped)
    return mapped


class MvpSemanticScoreResolver:
    def __init__(self, records: tuple[Mapping[str, Any], ...]) -> None:
        self._records = {
            (str(record["video_id"]), str(record["window_id"])): dict(record)
            for record in records
        }
        self._decoded: list[tuple[str, str]] = []

    @property
    def decoded_windows(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._decoded)

    def map_evidence(
        self,
        video_id: str,
        window: Mapping[str, Any],
        raw_vlm: Mapping[str, Any],
    ) -> dict[str, Any]:
        key = (video_id, str(window["window_id"]))
        if key in self._decoded:
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "semantic score was decoded more than once")
        record = self._records.get(key)
        if record is None or int(record["window_ordinal"]) != int(window["ordinal"]):
            raise fatal("MVP_FREEZE_INVALID", "semantic score identity is invalid")
        if payload_hash(dict(raw_vlm)) != str(record["source_vlm_payload_hash"]):
            raise fatal("MVP_FREEZE_INVALID", "semantic score source evidence binding is invalid")
        self._decoded.append(key)
        return semantic_score_to_evidence(raw_vlm, float(record["anomaly_score"]))


def load_semantic_score_manifest(
    manifest_path: Path,
    *,
    expected_sha256: str,
    input_manifest_path: Path,
) -> MvpSemanticScoreResolver:
    validate_path_identity(manifest_path)
    if (
        not manifest_path.is_file()
        or manifest_path.is_symlink()
        or len(expected_sha256) != 64
        or file_sha256(manifest_path) != expected_sha256
    ):
        raise fatal("MVP_FREEZE_INVALID", "semantic score manifest hash binding is invalid")
    try:
        manifest = loads(manifest_path.read_bytes())
        if not isinstance(manifest, dict):
            raise ValueError("object required")
    except MvpFailure:
        raise
    except Exception as exc:
        raise _safe_failure("semantic score manifest is unreadable", exc) from exc
    validate_inference_boundary(manifest)
    if set(manifest) != _MANIFEST_FIELDS:
        raise fatal("MVP_FREEZE_INVALID", "semantic score manifest fields are not closed")
    fixture, bundle, _evidence = load_precomputed_input(input_manifest_path)
    if (
        manifest["manifest_type"] != SEMANTIC_SCORE_MANIFEST_TYPE
        or manifest["adapter_identity"] != SEMANTIC_SCORER_IDENTITY
        or manifest["mapping_identity"] != MAPPING_IDENTITY
        or manifest["runtime_profile"] != RUNTIME_PROFILE
        or manifest["research_claim_status"] != RESEARCH_CLAIM_STATUS
        or manifest["context_prompt"] != ORIGINAL_CONTEXT_PROMPT
        or manifest["format_prompt"] != ORIGINAL_FORMAT_PROMPT
        or manifest["sampling"] != SAMPLING_CONFIG
        or manifest["input_manifest_sha256"] != file_sha256(input_manifest_path)
        or manifest["source_bundle_manifest_sha256"] != fixture["asset_bundle_manifest_sha256"]
    ):
        raise fatal("MVP_FREEZE_INVALID", "semantic score manifest provenance is invalid")
    inputs = _caption_inputs(input_manifest_path, fixture, bundle)
    scores = manifest["scores"]
    if not isinstance(scores, list) or manifest["score_count"] != len(scores) or len(scores) != len(inputs):
        raise fatal("MVP_FREEZE_INVALID", "semantic score manifest is incomplete")
    normalized: list[dict[str, Any]] = []
    for expected, record in zip(inputs, scores, strict=True):
        if not isinstance(record, dict) or set(record) != _SCORE_FIELDS:
            raise fatal("MVP_FREEZE_INVALID", "semantic score fields are not closed")
        if any(record[key] != expected[key] for key in expected if key != "caption"):
            raise fatal("MVP_FREEZE_INVALID", "semantic score source identity is invalid")
        score = record["anomaly_score"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0.0 <= float(score) <= 1.0
            or record["parse_status"] not in {"PARSED", "INTERPOLATED"}
            or not isinstance(record["raw_response"], str)
        ):
            raise fatal("MVP_FREEZE_INVALID", "semantic score value is invalid")
        normalized.append(dict(record))
    return MvpSemanticScoreResolver(tuple(normalized))


def precompute_semantic_scores(
    *,
    input_manifest_path: Path,
    output_root: Path,
    backend: MvpSemanticScoringBackend,
) -> MvpSemanticScoreReceipt:
    fixture, bundle, _evidence = load_precomputed_input(input_manifest_path)
    inputs = _caption_inputs(input_manifest_path, fixture, bundle)
    validate_path_identity(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "semantic score output root must be fresh")
    try:
        responses = backend.score(tuple(str(item["caption"]) for item in inputs))
    except MvpFailure:
        raise
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "semantic scoring backend failed") from exc
    finally:
        backend.close()
    if len(responses) != len(inputs) or any(not isinstance(response, str) for response in responses):
        raise fatal("ASSET_NOT_RUN", "semantic scoring backend returned an invalid response count")
    parsed = tuple(_parse_score(response) for response in responses)
    scores: list[dict[str, Any]] = []
    offset = 0
    for video in fixture["videos"]:
        count = len(video["windows"])
        video_parsed = parsed[offset : offset + count]
        video_scores = _interpolate(video_parsed)
        for item, response, parsed_score, score in zip(
            inputs[offset : offset + count],
            responses[offset : offset + count],
            video_parsed,
            video_scores,
            strict=True,
        ):
            scores.append(
                {
                    "anomaly_score": score,
                    "caption_payload_hash": item["caption_payload_hash"],
                    "parse_status": "PARSED" if parsed_score is not None else "INTERPOLATED",
                    "raw_response": response,
                    "source_vlm_payload_hash": item["source_vlm_payload_hash"],
                    "video_id": item["video_id"],
                    "window_id": item["window_id"],
                    "window_ordinal": item["window_ordinal"],
                }
            )
        offset += count
    provenance = dict(backend.provenance)
    validate_inference_boundary(provenance)
    manifest = {
        "adapter_identity": SEMANTIC_SCORER_IDENTITY,
        "backend_identity": str(backend.identity),
        "context_prompt": ORIGINAL_CONTEXT_PROMPT,
        "format_prompt": ORIGINAL_FORMAT_PROMPT,
        "input_manifest_sha256": file_sha256(input_manifest_path),
        "manifest_type": SEMANTIC_SCORE_MANIFEST_TYPE,
        "mapping_identity": MAPPING_IDENTITY,
        "model_provenance": provenance,
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "sampling": dict(SAMPLING_CONFIG),
        "score_count": len(scores),
        "scores": scores,
        "source_bundle_manifest_sha256": fixture["asset_bundle_manifest_sha256"],
    }
    validate_inference_boundary(manifest)
    candidate = dumps(manifest)
    parents = [file_sha256(input_manifest_path), str(fixture["asset_bundle_manifest_sha256"])]
    model_files = provenance.get("model_files", ())
    if isinstance(model_files, (list, tuple)):
        parents.extend(str(record["sha256"]) for record in model_files if isinstance(record, Mapping))
    publisher = MvpImmutablePublisher(output_root, {"manifest": "mvp_semantic_score_manifest.json"})
    receipt = publisher.publish(
        "manifest",
        candidate,
        payload_hash(manifest),
        parent_payload_hashes=tuple(parents),
    )
    return MvpSemanticScoreReceipt(output_root / receipt.relative_ref, receipt.file_hash, len(scores))


def _model_inventory(model_path: Path) -> tuple[dict[str, Any], ...]:
    validate_path_identity(model_path)
    if not model_path.is_dir() or model_path.is_symlink():
        raise fatal("ASSET_NOT_RUN", "semantic scoring model is unavailable")
    files = tuple(sorted((path for path in model_path.rglob("*") if path.is_file()), key=lambda path: path.as_posix()))
    if not files:
        raise fatal("ASSET_NOT_RUN", "semantic scoring model is empty")
    return tuple(
        {
            "byte_length": path.stat().st_size,
            "relative_ref": path.relative_to(model_path).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in files
    )


class TransformersSemanticScoringBackend:
    identity = SEMANTIC_SCORER_IDENTITY

    def __init__(self, model_path: Path, gpu_device: str, *, batch_size: int = 32) -> None:
        if not gpu_device.strip() or batch_size <= 0:
            raise ValueError("semantic scoring requires an explicit GPU and positive batch size")
        existing = os.environ.get("CUDA_VISIBLE_DEVICES")
        if existing is not None and existing != gpu_device:
            raise fatal("ASSET_NOT_RUN", "CUDA device binding conflicts with semantic scoring")
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu_device
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

        if not torch.cuda.is_available():
            raise fatal("ASSET_NOT_RUN", "CUDA is required for LLM semantic scoring")
        self._torch = torch
        self._batch_size = batch_size
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
        )
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        self._tokenizer.padding_side = "left"
        set_seed(int(SAMPLING_CONFIG["seed"]))
        self._model = AutoModelForCausalLM.from_pretrained(
            model_path,
            attn_implementation=ATTENTION_IMPLEMENTATION,
            device_map="auto",
            local_files_only=True,
            low_cpu_mem_usage=True,
            torch_dtype=torch.bfloat16,
            trust_remote_code=False,
        )
        self._model.eval()
        self.provenance = {
            "attention_implementation": ATTENTION_IMPLEMENTATION,
            "model_id": model_path.name,
            "model_files": list(_model_inventory(model_path)),
            "torch_version": str(torch.__version__),
            "transformers_version": str(transformers.__version__),
        }

    def score(self, captions: tuple[str, ...]) -> tuple[str, ...]:
        responses: list[str] = []
        system_prompt = f"{ORIGINAL_CONTEXT_PROMPT} {ORIGINAL_FORMAT_PROMPT}"
        for offset in range(0, len(captions), self._batch_size):
            batch = captions[offset : offset + self._batch_size]
            prompts = [
                self._tokenizer.apply_chat_template(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"{caption}."},
                    ],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                for caption in batch
            ]
            encoded = self._tokenizer(prompts, return_tensors="pt", padding=True)
            device = next(self._model.parameters()).device
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with self._torch.inference_mode():
                generated = self._model.generate(
                    **encoded,
                    do_sample=True,
                    max_new_tokens=int(SAMPLING_CONFIG["max_new_tokens"]),
                    pad_token_id=self._tokenizer.pad_token_id,
                    temperature=float(SAMPLING_CONFIG["temperature"]),
                    top_p=float(SAMPLING_CONFIG["top_p"]),
                )
            prompt_width = int(encoded["input_ids"].shape[1])
            responses.extend(
                self._tokenizer.decode(row[prompt_width:], skip_special_tokens=True).strip()
                for row in generated
            )
        return tuple(responses)

    def close(self) -> None:
        if hasattr(self, "_model"):
            del self._model
        if hasattr(self, "_torch") and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
