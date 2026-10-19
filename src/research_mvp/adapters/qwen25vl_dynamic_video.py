from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .. import RESEARCH_CLAIM_STATUS, RUNTIME_PROFILE
from ..artifacts.hashes import bytes_sha256, file_sha256
from ..artifacts.publisher import MvpImmutablePublisher
from ..artifacts.resolver import resolve_relative, validate_path_identity
from ..codec import dumps, payload_hash
from ..failures import MvpFailure, fatal
from ..media import frame_boundary_us
from ..schemas.dynamic_video_events import normalize_dynamic_observation
from .real_assets import load_asset_source_manifest, load_precomputed_input


DYNAMIC_VIDEO_MANIFEST_TYPE = "MVP_DYNAMIC_VIDEO_EVENT_MANIFEST_V1"
SAMPLED_FRAME_MANIFEST_TYPE = "MVP_DYNAMIC_VIDEO_SAMPLED_FRAMES_V1"
DYNAMIC_VIDEO_ADAPTER_IDENTITY = "QWEN25VL_DYNAMIC_VIDEO_EVENTS_MVP_V1"
SAMPLER_IDENTITY = "SOURCE_MANIFEST_FRAME_REFS_SHA256_V1"
PROMPT_CONFIG_IDENTITY = "DYNAMIC_EVENT_PROMPT_V1"
PARSED = "PARSED"
REPAIRED_SYNTAX = "REPAIRED_SYNTAX"
FAILED_RAW_SAVED = "FAILED_RAW_SAVED"
DEFAULT_SYSTEM_PROMPT = (
    "You are a video event analyst for zero-shot open-world surveillance understanding. "
    "Describe observable dynamic events in a video clip. Do not infer dataset labels, identities, "
    "intentions, or a final anomaly score. Focus on visible changes, actions, temporal order, "
    "uncertainty, and missing evidence. Output strict JSON only."
)
DEFAULT_USER_PROMPT = (
    "Analyze the provided surveillance video segment as a continuous event, not as independent frames. "
    "Return strict JSON with: window_start_sec, window_end_sec, summary, events, temporal_relations, "
    "safety_relevant_observations, missing_evidence, global_uncertainty, parse_notes. Each event must include: "
    "event_id, start_sec, end_sec, subject, action, object, location, state_change, event_type, "
    "motion_pattern, state_change_type, visibility, risk_cues, normal_cues, uncertainty, confidence."
)
DATASET_TERMS = (
    "abuse",
    "arrest",
    "arson",
    "assault",
    "burglary",
    "explosion",
    "fighting",
    "roadaccidents",
    "road accidents",
    "robbery",
    "shooting",
    "shoplifting",
    "stealing",
    "vandalism",
)


class DynamicVideoBackend(Protocol):
    identity: str
    provenance: Mapping[str, Any]

    def describe(self, request: Mapping[str, Any]) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DynamicVideoPrecomputeReceipt:
    manifest_path: Path
    manifest_sha256: str
    observation_count: int
    parse_success_count: int
    status_code: str = "DYNAMIC_VIDEO_EVENTS_FROZEN"


def _prompt_payload() -> dict[str, str]:
    return {
        "prompt_config_identity": PROMPT_CONFIG_IDENTITY,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt": DEFAULT_USER_PROMPT,
    }


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    fence = chr(96) * 3
    if stripped.startswith(fence) and stripped.endswith(fence):
        inner = stripped[len(fence) : -len(fence)].strip()
        if inner.casefold().startswith("json"):
            inner = inner[4:].strip()
        return inner
    return stripped


def _extract_json_object(text: str) -> str:
    stripped = _strip_fence(text)
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def parse_dynamic_video_output(
    raw_output: str,
    *,
    window_start_sec: float,
    window_end_sec: float,
) -> tuple[dict[str, Any] | None, str, tuple[str, ...], str, str]:
    raw_text = str(raw_output)
    extracted = _extract_json_object(raw_text)
    candidates: list[tuple[str, str]] = [(raw_text, "")]
    if extracted != raw_text:
        candidates.append((extracted, "EXTRACT_JSON_OBJECT"))
    trailing_fixed = re.sub(r",\s*([}\]])", r"\1", extracted)
    if trailing_fixed != extracted:
        candidates.append((trailing_fixed, "EXTRACT_JSON_OBJECT|REMOVE_TRAILING_COMMAS"))
    errors: list[str] = []
    for candidate, repair_diff in candidates:
        try:
            decoded = json.loads(candidate)
            if not isinstance(decoded, dict):
                raise ValueError("object required")
            observation, warnings = normalize_dynamic_observation(
                decoded,
                window_start_sec=window_start_sec,
                window_end_sec=window_end_sec,
            )
            status = PARSED if not repair_diff else REPAIRED_SYNTAX
            return observation, status, warnings, repair_diff, ""
        except Exception as exc:
            errors.append(type(exc).__name__)
    return None, FAILED_RAW_SAVED, (), "", "|".join(errors[-3:])


def detect_dataset_terms(text: str) -> tuple[str, ...]:
    lowered = str(text).casefold()
    found = {term for term in DATASET_TERMS if term in lowered}
    return tuple(sorted(found, key=lambda item: item.encode("utf-8")))


def _source_lookup(source: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(video["video_id"]), str(window["window_id"])): window
        for video in source["videos"]
        for window in video["windows"]
    }


def _source_video_lookup(source: Mapping[str, Any], asset_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for video in source["videos"]:
        path = resolve_relative(asset_root, str(video["video_ref"]))
        result[str(video["video_id"])] = {
            "byte_length": path.stat().st_size,
            "relative_ref": str(video["video_ref"]),
            "sha256": file_sha256(path),
        }
    return result


def _sampled_frame_manifest(
    *,
    video_id: str,
    source_window: Mapping[str, Any],
    asset_root: Path,
    source_video: Mapping[str, Any],
    fps_num: int,
    fps_den: int,
) -> dict[str, Any]:
    refs = source_window["frame_refs"]
    indices = source_window.get("sampled_frame_indices", [])
    timestamps = source_window.get("sampled_frame_timestamps_us", [])
    if not isinstance(refs, list) or not refs:
        raise fatal("MVP_FREEZE_INVALID", "dynamic video source has no sampled frames")
    if len(indices) != len(refs):
        indices = list(range(int(source_window["evidence_start_frame"]), int(source_window["evidence_start_frame"]) + len(refs)))
    if len(timestamps) != len(refs):
        timestamps = [frame_boundary_us(int(index), fps_num, fps_den) for index in indices]
    frames = []
    for relative, index, timestamp in zip(refs, indices, timestamps, strict=True):
        path = resolve_relative(asset_root, str(relative))
        if not path.is_file() or path.is_symlink():
            raise fatal("MVP_FREEZE_INVALID", "dynamic sampled frame is unavailable")
        frames.append(
            {
                "byte_length": path.stat().st_size,
                "relative_ref": str(relative),
                "sha256": file_sha256(path),
                "source_frame_index": int(index),
                "timestamp_us": int(timestamp),
            }
        )
    return {
        "decision_end_frame": int(source_window["end_frame"]),
        "decision_end_us": int(source_window["end_us"]),
        "decision_start_frame": int(source_window["start_frame"]),
        "decision_start_us": int(source_window["start_us"]),
        "evidence_end_frame": int(source_window["evidence_end_frame"]),
        "evidence_end_us": int(source_window["evidence_end_us"]),
        "evidence_start_frame": int(source_window["evidence_start_frame"]),
        "evidence_start_us": int(source_window["evidence_start_us"]),
        "frames": frames,
        "manifest_type": SAMPLED_FRAME_MANIFEST_TYPE,
        "sampler_config_hash": payload_hash({"sampler_identity": SAMPLER_IDENTITY, "source_window": dict(source_window)}),
        "sampler_identity": SAMPLER_IDENTITY,
        "source_video": dict(source_video),
        "video_id": video_id,
        "window_id": str(source_window["window_id"]),
        "window_ordinal": int(source_window["ordinal"]),
    }


def _model_request(frame_manifest: Mapping[str, Any], asset_root: Path) -> dict[str, Any]:
    prompt = _prompt_payload()
    return {
        "frame_count": len(frame_manifest["frames"]),
        "frame_paths": [str(resolve_relative(asset_root, str(row["relative_ref"]))) for row in frame_manifest["frames"]],
        "frame_sha256": [str(row["sha256"]) for row in frame_manifest["frames"]],
        "prompt": prompt,
        "window_end_sec": int(frame_manifest["evidence_end_us"]) / 1_000_000,
        "window_start_sec": int(frame_manifest["evidence_start_us"]) / 1_000_000,
    }


def precompute_dynamic_video_events(
    *,
    input_manifest_path: Path,
    source_manifest_path: Path,
    asset_root: Path,
    output_root: Path,
    backend: DynamicVideoBackend,
) -> DynamicVideoPrecomputeReceipt:
    fixture, _bundle, _resolver = load_precomputed_input(input_manifest_path)
    source = load_asset_source_manifest(source_manifest_path, asset_root)
    validate_path_identity(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "dynamic video output root must be fresh")
    if file_sha256(source_manifest_path) != str(fixture["source_manifest_sha256"]):
        raise fatal("MVP_FREEZE_INVALID", "dynamic video source manifest does not match input manifest")
    fps = source["frame_rate"]
    fps_num, fps_den = int(fps["numerator"]), int(fps["denominator"])
    source_windows = _source_lookup(source)
    source_videos = _source_video_lookup(source, asset_root)

    planned = {"manifest": "manifest.json", "model_io": "model_io/qwen_dynamic_io.jsonl"}
    for video in fixture["videos"]:
        planned[f"observations:{video['video_id']}"] = f"observations/{video['video_id']}.jsonl"
        for window in video["windows"]:
            prefix = f"{video['video_id']}/{window['window_id']}"
            planned[f"frames:{prefix}"] = f"sampled_frames/{prefix}.json"
            planned[f"raw:{prefix}"] = f"raw_model_outputs/{prefix}.txt"
    publisher = MvpImmutablePublisher(output_root, planned)
    records_by_video: dict[str, list[dict[str, Any]]] = {str(video["video_id"]): [] for video in fixture["videos"]}
    io_rows: list[dict[str, Any]] = []
    observation_records: list[dict[str, Any]] = []

    try:
        for video in fixture["videos"]:
            video_id = str(video["video_id"])
            for window in video["windows"]:
                window_id = str(window["window_id"])
                key = (video_id, window_id)
                source_window = source_windows.get(key)
                if source_window is None or int(source_window["ordinal"]) != int(window["ordinal"]):
                    raise fatal("MVP_WINDOW_ORDER_VIOLATION", "dynamic video source window is missing")
                frame_manifest = _sampled_frame_manifest(
                    video_id=video_id,
                    source_window=source_window,
                    asset_root=asset_root,
                    source_video=source_videos[video_id],
                    fps_num=fps_num,
                    fps_den=fps_den,
                )
                frame_bytes = dumps(frame_manifest)
                frame_receipt = publisher.publish(
                    f"frames:{video_id}/{window_id}",
                    frame_bytes,
                    bytes_sha256(frame_bytes),
                    semantic_payload_hash=payload_hash(frame_manifest),
                    parent_payload_hashes=(str(fixture["source_manifest_sha256"]),),
                )
                request = _model_request(frame_manifest, asset_root)
                raw_output = backend.describe(request)
                raw_bytes = str(raw_output).encode("utf-8", errors="strict")
                raw_receipt = publisher.publish(
                    f"raw:{video_id}/{window_id}",
                    raw_bytes,
                    bytes_sha256(raw_bytes),
                    parent_payload_hashes=(frame_receipt.payload_hash, payload_hash(_prompt_payload())),
                )
                start_sec = int(frame_manifest["evidence_start_us"]) / 1_000_000
                end_sec = int(frame_manifest["evidence_end_us"]) / 1_000_000
                observation, parse_status, warnings, repair_diff, error_reason = parse_dynamic_video_output(
                    str(raw_output),
                    window_start_sec=start_sec,
                    window_end_sec=end_sec,
                )
                leakage_terms = detect_dataset_terms(str(raw_output))
                record = {
                    "dataset_term_leakage_terms": list(leakage_terms),
                    "error_reason": error_reason,
                    "frame_end": int(window["end_frame"]),
                    "frame_start": int(window["start_frame"]),
                    "input_segment_hash": frame_receipt.payload_hash,
                    "observation": observation,
                    "parse_status": parse_status,
                    "parse_warnings": list(warnings),
                    "prompt_sha256": payload_hash(_prompt_payload()),
                    "raw_output_ref": raw_receipt.relative_ref,
                    "raw_output_sha256": raw_receipt.file_hash,
                    "repair_diff": repair_diff,
                    "sampled_frame_manifest_ref": frame_receipt.relative_ref,
                    "sampled_frame_manifest_sha256": frame_receipt.file_hash,
                    "video_id": video_id,
                    "window_id": window_id,
                    "window_ordinal": int(window["ordinal"]),
                }
                records_by_video[video_id].append(record)
                observation_records.append(record)
                io_rows.append(
                    {
                        "dataset_term_leakage_terms": list(leakage_terms),
                        "input_segment_hash": frame_receipt.payload_hash,
                        "model_input": {
                            "frame_count": request["frame_count"],
                            "frame_sha256": request["frame_sha256"],
                            "prompt_sha256": payload_hash(_prompt_payload()),
                            "window_end_sec": request["window_end_sec"],
                            "window_start_sec": request["window_start_sec"],
                        },
                        "parse_status": parse_status,
                        "raw_output_ref": raw_receipt.relative_ref,
                        "raw_output_sha256": raw_receipt.file_hash,
                        "video_id": video_id,
                        "window_id": window_id,
                        "window_ordinal": int(window["ordinal"]),
                    }
                )
    except MvpFailure:
        raise
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "dynamic video backend failed") from exc
    finally:
        backend.close()

    observation_files: list[dict[str, Any]] = []
    for video_id, rows in records_by_video.items():
        content = b"\n".join(dumps(row) for row in rows) + b"\n"
        receipt = publisher.publish(
            f"observations:{video_id}",
            content,
            bytes_sha256(content),
            parent_payload_hashes=tuple(str(row["input_segment_hash"]) for row in rows),
        )
        observation_files.append(
            {
                "byte_length": receipt.byte_length,
                "relative_ref": receipt.relative_ref,
                "sha256": receipt.file_hash,
                "video_id": video_id,
                "window_count": len(rows),
            }
        )
    io_content = b"\n".join(dumps(row) for row in io_rows) + b"\n"
    io_receipt = publisher.publish(
        "model_io",
        io_content,
        bytes_sha256(io_content),
        parent_payload_hashes=tuple(str(row["input_segment_hash"]) for row in observation_records),
    )
    provenance = dict(backend.provenance)
    manifest = {
        "adapter_identity": DYNAMIC_VIDEO_ADAPTER_IDENTITY,
        "backend_identity": str(backend.identity),
        "dataset_id": str(fixture["dataset_id"]),
        "dataset_term_leakage_count": sum(1 for row in observation_records if row["dataset_term_leakage_terms"]),
        "input_manifest_sha256": file_sha256(input_manifest_path),
        "manifest_type": DYNAMIC_VIDEO_MANIFEST_TYPE,
        "model_io": {
            "byte_length": io_receipt.byte_length,
            "relative_ref": io_receipt.relative_ref,
            "sha256": io_receipt.file_hash,
        },
        "model_provenance": provenance,
        "observation_count": len(observation_records),
        "observation_files": observation_files,
        "parse_failure_count": sum(1 for row in observation_records if row["parse_status"] == FAILED_RAW_SAVED),
        "parse_repaired_count": sum(1 for row in observation_records if row["parse_status"] == REPAIRED_SYNTAX),
        "parse_success_count": sum(1 for row in observation_records if row["parse_status"] in {PARSED, REPAIRED_SYNTAX}),
        "prompt_config": _prompt_payload(),
        "prompt_sha256": payload_hash(_prompt_payload()),
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "sampler_identity": SAMPLER_IDENTITY,
        "source_asset_profile": fixture.get("asset_profile", "ALL"),
        "source_bundle_manifest_sha256": str(fixture["asset_bundle_manifest_sha256"]),
        "source_manifest_sha256": str(fixture["source_manifest_sha256"]),
        "temporal_protocol": str(fixture.get("temporal_protocol")),
        "window_grid": {
            "decision_stride_frames": fixture.get("decision_stride_frames"),
            "evidence_context_frames": fixture.get("evidence_context_frames"),
            "frame_rate": fixture.get("frame_rate"),
        },
    }
    manifest_bytes = dumps(manifest)
    parents = [
        file_sha256(input_manifest_path),
        str(fixture["source_manifest_sha256"]),
        str(fixture["asset_bundle_manifest_sha256"]),
        io_receipt.file_hash,
        *(row["sha256"] for row in observation_files),
    ]
    final = publisher.publish(
        "manifest",
        manifest_bytes,
        bytes_sha256(manifest_bytes),
        semantic_payload_hash=payload_hash(manifest),
        parent_payload_hashes=tuple(parents),
    )
    return DynamicVideoPrecomputeReceipt(
        manifest_path=output_root / final.relative_ref,
        manifest_sha256=final.file_hash,
        observation_count=len(observation_records),
        parse_success_count=int(manifest["parse_success_count"]),
    )


class DeterministicDynamicVideoBackend:
    identity = "DETERMINISTIC_DYNAMIC_VIDEO_BACKEND_TEST_V1"

    def __init__(self) -> None:
        self.provenance = {"backend": self.identity, "purpose": "contract-test-only"}

    def describe(self, request: Mapping[str, Any]) -> str:
        start = float(request["window_start_sec"])
        end = float(request["window_end_sec"])
        return json.dumps(
            {
                "events": [
                    {
                        "action": "standing",
                        "confidence": 0.6,
                        "end_sec": end,
                        "event_id": "e1",
                        "event_type": "stable_scene",
                        "location": "surveillance scene",
                        "motion_pattern": "standing",
                        "normal_cues": ["stable visible scene"],
                        "object": "unknown",
                        "risk_cues": [],
                        "start_sec": start,
                        "state_change": "no clear change",
                        "state_change_type": "no_change",
                        "subject": "people or scene",
                        "uncertainty": "medium",
                        "visibility": "partial",
                    }
                ],
                "global_uncertainty": "medium",
                "missing_evidence": [],
                "parse_notes": "",
                "safety_relevant_observations": [],
                "summary": "The visible scene remains mostly stable in the sampled frames.",
                "temporal_relations": [],
                "window_end_sec": end,
                "window_start_sec": start,
            },
            ensure_ascii=False,
        )

    def close(self) -> None:
        return None


class Qwen25VLDynamicVideoBackend:
    identity = "QWEN2_5_VL_7B_DYNAMIC_VIDEO_BACKEND_V1"

    def __init__(self, model_path: Path, gpu_device: str, *, max_new_tokens: int = 768) -> None:
        if not gpu_device.strip():
            raise ValueError("qwen backend requires an explicit gpu_device")
        existing = os.environ.get("CUDA_VISIBLE_DEVICES")
        if existing is not None and existing != gpu_device:
            raise fatal("ASSET_NOT_RUN", "CUDA device binding conflicts with dynamic video backend")
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu_device
        validate_path_identity(model_path)
        if not model_path.is_dir() or model_path.is_symlink():
            raise fatal("ASSET_NOT_RUN", "Qwen2.5-VL model path is unavailable")
        import torch
        import transformers
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        if not torch.cuda.is_available():
            raise fatal("ASSET_NOT_RUN", "CUDA is required for Qwen2.5-VL dynamic video precompute")
        self._torch = torch
        self._max_new_tokens = max_new_tokens
        self._processor = AutoProcessor.from_pretrained(model_path, local_files_only=True, trust_remote_code=True)
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_path,
            device_map="auto",
            local_files_only=True,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
        )
        self._model.eval()
        self.provenance = {
            "max_new_tokens": max_new_tokens,
            "model_id": model_path.name,
            "model_path": str(model_path),
            "torch_version": str(torch.__version__),
            "transformers_version": str(transformers.__version__),
        }

    def describe(self, request: Mapping[str, Any]) -> str:
        from PIL import Image

        frames = [Image.open(path).convert("RGB") for path in request["frame_paths"]]
        prompt = request["prompt"]
        messages = [
            {"role": "system", "content": [{"type": "text", "text": str(prompt["system_prompt"])}]},
            {
                "role": "user",
                "content": [
                    *({"type": "image", "image": frame} for frame in frames),
                    {"type": "text", "text": str(prompt["user_prompt"])},
                ],
            },
        ]
        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._processor(text=[text], images=frames, return_tensors="pt").to(self._model.device)
        with self._torch.inference_mode():
            generated = self._model.generate(**inputs, max_new_tokens=self._max_new_tokens, do_sample=False)
        prompt_width = int(inputs["input_ids"].shape[1])
        return self._processor.batch_decode(generated[:, prompt_width:], skip_special_tokens=True)[0].strip()

    def close(self) -> None:
        if hasattr(self, "_model"):
            del self._model
        if hasattr(self, "_torch") and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
