from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .. import RESEARCH_CLAIM_STATUS, RUNTIME_PROFILE
from ..artifacts.hashes import file_sha256
from ..artifacts.publisher import MvpImmutablePublisher
from ..artifacts.resolver import resolve_relative, validate_path_identity
from ..codec import dumps, loads, payload_hash
from ..config import validate_inference_boundary
from ..failures import MvpFailure, fatal
from ..ids import validate_attempt_id, window_semantic_id
from ..media import SOURCE_MANIFEST_TYPE as SOURCE_MANIFEST_TYPE_V1
from ..media import TEMPORAL_PROTOCOLS, plan_video_windows


SOURCE_MANIFEST_TYPE_V0 = "MVP_REAL_ASSET_SOURCE_V0"
PRECOMPUTED_MANIFEST_TYPE_V0 = "MVP_PRECOMPUTED_INPUT_V0"
PRECOMPUTED_MANIFEST_TYPE_V1 = "MVP_PRECOMPUTED_INPUT_V1"
ADAPTER_IDENTITY_V0 = "PRECOMPUTED_REAL_ASSET_EVIDENCE_MVP_V0"
ADAPTER_IDENTITY_V1 = "PRECOMPUTED_REAL_ASSET_EVIDENCE_MVP_V1"
SMOKE_MAPPER_IDENTITY = "MVP_SMOKE_TEXT_EVIDENCE_V0"

_TOKEN = re.compile(r"[a-z0-9_]+")
_RISK_CUES = frozenset(
    {
        "abuse",
        "alarm",
        "arson",
        "assault",
        "attack",
        "blood",
        "breakin",
        "burglary",
        "crash",
        "distress_audio",
        "explosion",
        "fight",
        "fire",
        "gun",
        "hit",
        "knife",
        "panic",
        "robbery",
        "scream",
        "smoke",
        "steal",
        "violence",
    }
)
_NORMAL_CUES = frozenset({"calm", "empty", "normal", "quiet", "safe", "sitting", "standing", "talking", "walk"})
_MODEL_FIELDS = ("caption_model", "ocr_model", "audio_model", "embedding_model")
_ACTION_CHANNEL = {"VLM": "VLM", "OCR": "OCR", "AUDIO": "ACOUSTIC_EVENT"}
_ACTION_FAMILY = {"VLM": "VISUAL", "OCR": "VISUAL", "AUDIO": "AUDIO"}


@dataclass(frozen=True, slots=True)
class MvpRealModelConfig:
    caption_model: Path
    ocr_model: Path
    audio_model: Path
    embedding_model: Path
    gpu_device: str
    caption_max_frames: int = 10
    caption_fps: int = 2
    caption_max_new_tokens: int = 256
    caption_temperature: float = 0.0
    audio_compute_type: str = "float16"
    ocr_languages: tuple[str, ...] = ("en",)

    def __post_init__(self) -> None:
        if not isinstance(self.gpu_device, str) or not self.gpu_device.strip():
            raise ValueError("gpu_device must be explicit")
        if self.caption_max_frames <= 0 or self.caption_fps <= 0 or self.caption_max_new_tokens <= 0:
            raise ValueError("caption sampling parameters must be positive")
        if not math.isfinite(self.caption_temperature) or self.caption_temperature < 0.0:
            raise ValueError("caption_temperature must be finite and non-negative")
        if not self.ocr_languages or any(not language for language in self.ocr_languages):
            raise ValueError("at least one OCR language is required")


@dataclass(frozen=True, slots=True)
class MvpAssetBundleReceipt:
    bundle_id: str
    bundle_manifest_path: Path
    bundle_manifest_sha256: str
    input_manifest_path: Path
    input_manifest_sha256: str
    status_code: str = "ASSET_BUNDLE_FROZEN"


class MvpRealBackends(Protocol):
    identity: str

    def caption(self, window: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def ocr(self, window: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def audio(self, window: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def embedding(self, text: str, window: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


def _safe_failure(code: str, message: str, exc: Exception | None = None) -> MvpFailure:
    failure = fatal(code, message)
    if exc is not None:
        failure.__cause__ = exc
    return failure


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(_TOKEN.findall(text.casefold())), key=lambda value: value.encode("utf-8")))


def smoke_evidence_direction(text: str) -> tuple[float, tuple[str, ...]]:
    """Frozen smoke-only mapper; it is operational evidence, never a research claim."""

    tokens = set(_tokens(text))
    risk = tokens & _RISK_CUES
    normal = tokens & _NORMAL_CUES
    cues = tuple(sorted(risk | normal, key=lambda value: value.encode("utf-8")))
    if risk and not normal:
        return 1.0, cues
    if normal and not risk:
        return -1.0, cues
    return 0.0, cues


def _read_object(path: Path, code: str) -> dict[str, Any]:
    try:
        decoded = loads(path.read_bytes())
        if not isinstance(decoded, dict):
            raise ValueError("object required")
        return decoded
    except MvpFailure:
        raise
    except Exception as exc:
        raise _safe_failure(code, "registered JSON artifact is unreadable", exc) from exc


def _require_file(root: Path, relative: str) -> Path:
    path = resolve_relative(root, relative)
    if not path.is_file() or path.is_symlink():
        raise fatal("ASSET_NOT_RUN", "a registered source asset is missing")
    validate_path_identity(path)
    return path


def _validate_window_id(video_id: str, ordinal: int, window_id: str) -> None:
    expected = window_semantic_id(video_id, ordinal)
    if window_id != expected:
        raise fatal("MVP_WINDOW_ORDER_VIOLATION", "real-asset window identity is not ordinal-derived")


def load_asset_source_manifest(source_manifest_path: Path, asset_root: Path) -> dict[str, Any]:
    validate_path_identity(source_manifest_path)
    validate_path_identity(asset_root)
    if not source_manifest_path.is_file() or not asset_root.is_dir():
        raise fatal("ASSET_NOT_RUN", "source manifest or asset root is unavailable")
    source = _read_object(source_manifest_path, "ASSET_NOT_RUN")
    validate_inference_boundary(source)
    manifest_type = source.get("manifest_type")
    v1 = manifest_type == SOURCE_MANIFEST_TYPE_V1
    required_root = (
        {
            "dataset_id",
            "decision_stride_frames",
            "evidence_context_frames",
            "frame_rate",
            "manifest_type",
            "runtime_profile",
            "temporal_protocol",
            "videos",
        }
        if v1
        else {"dataset_id", "manifest_type", "runtime_profile", "videos"}
    )
    if set(source) != required_root:
        raise fatal("MVP_FREEZE_INVALID", "source manifest fields are not closed")
    if manifest_type not in {SOURCE_MANIFEST_TYPE_V0, SOURCE_MANIFEST_TYPE_V1} or source["runtime_profile"] != RUNTIME_PROFILE:
        raise fatal("MVP_FREEZE_INVALID", "source manifest profile is invalid")
    if not isinstance(source["dataset_id"], str) or not source["dataset_id"]:
        raise fatal("MVP_FREEZE_INVALID", "dataset identity is invalid")
    fps_num = 0
    fps_den = 0
    decision_stride_frames = 0
    evidence_context_frames = 0
    temporal_protocol = ""
    if v1:
        rate = source["frame_rate"]
        if not isinstance(rate, dict) or set(rate) != {"denominator", "numerator"}:
            raise fatal("MVP_TIME_INVALID", "source frame rate fields are invalid")
        fps_num = rate["numerator"]
        fps_den = rate["denominator"]
        decision_stride_frames = source["decision_stride_frames"]
        evidence_context_frames = source["evidence_context_frames"]
        for value in (fps_num, fps_den, decision_stride_frames, evidence_context_frames):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise fatal("MVP_TIME_INVALID", "source temporal parameters must be positive integers")
        temporal_protocol = str(source["temporal_protocol"])
        if temporal_protocol not in TEMPORAL_PROTOCOLS:
            raise fatal("MVP_TIME_INVALID", "source temporal protocol is unregistered")
    videos = source["videos"]
    if not isinstance(videos, list) or not videos:
        raise fatal("MVP_FREEZE_INVALID", "source manifest requires ordered videos")
    seen_videos: set[str] = set()
    seen_windows: set[str] = set()
    for video in videos:
        required_video = {"frame_count", "video_id", "video_ref", "windows"} if v1 else {"video_id", "video_ref", "windows"}
        if not isinstance(video, dict) or set(video) != required_video:
            raise fatal("MVP_FREEZE_INVALID", "source video fields are not closed")
        video_id = str(video["video_id"])
        try:
            window_semantic_id(video_id, 0)
        except ValueError as exc:
            raise _safe_failure("MVP_FREEZE_INVALID", "source video identity is invalid", exc) from exc
        if video_id in seen_videos:
            raise fatal("MVP_WINDOW_ORDER_VIOLATION", "duplicate source video")
        seen_videos.add(video_id)
        _require_file(asset_root, str(video["video_ref"]))
        windows = video["windows"]
        if not isinstance(windows, list) or not windows:
            raise fatal("MVP_FREEZE_INVALID", "source video requires ordered windows")
        expected_windows = None
        if v1:
            frame_count = video["frame_count"]
            if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
                raise fatal("MVP_TIME_INVALID", "source frame count is invalid")
            expected_windows = plan_video_windows(
                video_id=video_id,
                frame_count=frame_count,
                fps_num=fps_num,
                fps_den=fps_den,
                temporal_protocol=temporal_protocol,
                decision_stride_frames=decision_stride_frames,
                evidence_context_frames=evidence_context_frames,
            )
            if len(windows) != len(expected_windows):
                raise fatal("MVP_WINDOW_ORDER_VIOLATION", "source prediction grid is incomplete")
        for expected_ordinal, window in enumerate(windows):
            required = {
                "audio_ref",
                "delta_us",
                "end_frame",
                "end_us",
                "frame_refs",
                "ordinal",
                "start_frame",
                "start_us",
                "window_id",
            }
            if v1:
                required.update(
                    {
                        "evidence_end_frame",
                        "evidence_end_us",
                        "evidence_start_frame",
                        "evidence_start_us",
                    }
                )
            if not isinstance(window, dict) or set(window) != required:
                raise fatal("MVP_FREEZE_INVALID", "source window fields are not closed")
            ordinal = window["ordinal"]
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal != expected_ordinal:
                raise fatal("MVP_WINDOW_ORDER_VIOLATION", "source windows are not contiguous and ordered")
            window_id = str(window["window_id"])
            try:
                _validate_window_id(video_id, ordinal, window_id)
            except ValueError as exc:
                raise _safe_failure("MVP_FREEZE_INVALID", "source window identity is invalid", exc) from exc
            if window_id in seen_windows:
                raise fatal("MVP_WINDOW_ORDER_VIOLATION", "duplicate source window")
            seen_windows.add(window_id)
            integer_fields = ["start_us", "end_us", "delta_us", "start_frame", "end_frame"]
            if v1:
                integer_fields.extend(
                    ["evidence_start_us", "evidence_end_us", "evidence_start_frame", "evidence_end_frame"]
                )
            for name in integer_fields:
                value = window[name]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise fatal("MVP_TIME_INVALID", "source time/frame facts must be integers")
            if window["start_us"] < 0 or window["end_us"] <= window["start_us"] or window["delta_us"] <= 0:
                raise fatal("MVP_TIME_INVALID", "source interval is invalid")
            if window["start_frame"] < 0 or window["end_frame"] < window["start_frame"]:
                raise fatal("MVP_TIME_INVALID", "source frame interval is invalid")
            if window["delta_us"] != window["end_us"] - window["start_us"]:
                raise fatal("MVP_TIME_INVALID", "source delta does not match decision boundaries")
            if v1:
                expected = expected_windows[expected_ordinal]
                exact_fields = (
                    "window_id",
                    "ordinal",
                    "start_frame",
                    "end_frame",
                    "start_us",
                    "end_us",
                    "delta_us",
                    "evidence_start_frame",
                    "evidence_end_frame",
                    "evidence_start_us",
                    "evidence_end_us",
                )
                if any(window[name] != getattr(expected, name) for name in exact_fields):
                    raise fatal("MVP_WINDOW_ORDER_VIOLATION", "source temporal grid does not match its protocol")
            frame_refs = window["frame_refs"]
            if not isinstance(frame_refs, list) or not frame_refs:
                raise fatal("ASSET_NOT_RUN", "source window has no frames")
            for frame_ref in frame_refs:
                _require_file(asset_root, str(frame_ref))
            _require_file(asset_root, str(window["audio_ref"]))
    return source


def _model_missing(config: MvpRealModelConfig) -> list[str]:
    missing: list[str] = []
    for name in _MODEL_FIELDS:
        path = getattr(config, name)
        try:
            validate_path_identity(path)
        except MvpFailure:
            raise
        if not path.exists() or path.is_symlink() or (path.is_dir() and not any(path.iterdir())):
            missing.append(name)
    return missing


def inspect_real_assets(
    source_manifest_path: Path,
    asset_root: Path,
    model_config: MvpRealModelConfig,
) -> dict[str, Any]:
    missing = _model_missing(model_config)
    source_ready = True
    try:
        source = load_asset_source_manifest(source_manifest_path, asset_root)
        video_count = len(source["videos"])
        window_count = sum(len(video["windows"]) for video in source["videos"])
    except MvpFailure as exc:
        if exc.code != "ASSET_NOT_RUN":
            raise
        source_ready = False
        video_count = 0
        window_count = 0
    ready = source_ready and not missing
    return {
        "missing_assets": missing + ([] if source_ready else ["source_assets"]),
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "status_code": "ASSET_READY" if ready else "ASSET_NOT_RUN",
        "video_count": video_count,
        "window_count": window_count,
    }


def _inventory_tree(path: Path, asset_id: str) -> tuple[dict[str, str], ...]:
    validate_path_identity(path)
    if path.is_file() and not path.is_symlink():
        files = (path,)
        base = path.parent
    elif path.is_dir() and not path.is_symlink():
        files = tuple(sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix().encode()))
        base = path
    else:
        raise fatal("ASSET_NOT_RUN", "model asset is unavailable")
    if not files:
        raise fatal("ASSET_NOT_RUN", "model asset contains no files")
    records: list[dict[str, str]] = []
    for file_path in files:
        validate_path_identity(file_path)
        if file_path.is_symlink():
            raise fatal("MVP_PATH_ESCAPE", "model asset traverses a symbolic link")
        records.append(
            {
                "model_id": asset_id,
                "relative_ref": file_path.relative_to(base).as_posix(),
                "sha256": file_sha256(file_path),
            }
        )
    return tuple(records)


def _source_inventory(source: Mapping[str, Any], asset_root: Path) -> tuple[dict[str, str], ...]:
    refs = {
        str(video["video_ref"])
        for video in source["videos"]
    }
    refs.update(str(window["audio_ref"]) for video in source["videos"] for window in video["windows"])
    refs.update(str(ref) for video in source["videos"] for window in video["windows"] for ref in window["frame_refs"])
    return tuple(
        {"relative_ref": relative, "sha256": file_sha256(_require_file(asset_root, relative))}
        for relative in sorted(refs, key=lambda value: value.encode("utf-8"))
    )


def _backend_window(video: Mapping[str, Any], window: Mapping[str, Any], asset_root: Path) -> dict[str, Any]:
    return {
        **dict(window),
        "audio_path": str(_require_file(asset_root, str(window["audio_ref"]))),
        "decision_end_frame": int(window["end_frame"]),
        "decision_end_us": int(window["end_us"]),
        "decision_start_frame": int(window["start_frame"]),
        "decision_start_us": int(window["start_us"]),
        "end_frame": int(window.get("evidence_end_frame", window["end_frame"])),
        "end_us": int(window.get("evidence_end_us", window["end_us"])),
        "frame_paths": [str(_require_file(asset_root, str(ref))) for ref in window["frame_refs"]],
        "start_frame": int(window.get("evidence_start_frame", window["start_frame"])),
        "start_us": int(window.get("evidence_start_us", window["start_us"])),
        "video_id": str(video["video_id"]),
        "video_path": str(_require_file(asset_root, str(video["video_ref"]))),
    }


def _confidence(value: Any) -> float:
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise fatal("ASSET_NOT_RUN", "backend confidence is invalid")
    return confidence


def _normalize_raw(action: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise fatal("ASSET_NOT_RUN", "backend returned a non-object")
    validate_inference_boundary(raw)
    backend_name = str(raw.get("backend_name", ""))
    if not backend_name:
        raise fatal("ASSET_NOT_RUN", "backend identity is missing")
    if action == "CAPTION":
        return {
            "backend_name": backend_name,
            "confidence": _confidence(raw.get("confidence", 0.0)),
            "text": str(raw.get("text", "")).strip(),
        }
    if action == "OCR":
        texts = raw.get("texts", ())
        if not isinstance(texts, (list, tuple)):
            raise fatal("ASSET_NOT_RUN", "OCR texts are invalid")
        return {
            "backend_name": backend_name,
            "confidence": _confidence(raw.get("confidence", 0.0)),
            "texts": [str(value).strip() for value in texts if str(value).strip()],
        }
    if action == "AUDIO":
        events = raw.get("events", ())
        if not isinstance(events, (list, tuple)):
            raise fatal("ASSET_NOT_RUN", "Audio events are invalid")
        return {
            "backend_name": backend_name,
            "confidence": _confidence(raw.get("confidence", 0.0)),
            "events": [str(value).strip() for value in events if str(value).strip()],
            "transcript": str(raw.get("transcript", "")).strip(),
        }
    if action == "EMBEDDING":
        if raw.get("fallback_used") is not False:
            raise fatal("ASSET_NOT_RUN", "fallback embedding is forbidden")
        vector = raw.get("vector")
        if not isinstance(vector, (list, tuple)) or not vector:
            raise fatal("ASSET_NOT_RUN", "embedding vector is missing")
        values = [float(value) for value in vector]
        if any(not math.isfinite(value) for value in values):
            raise fatal("ASSET_NOT_RUN", "embedding vector is non-finite")
        return {"backend_name": backend_name, "fallback_used": False, "vector": values}
    raise ValueError("unknown backend action")


def _action_text(action: str, raw: Mapping[str, Any]) -> str:
    if action == "VLM":
        return str(raw["text"])
    if action == "OCR":
        return " ".join(str(value) for value in raw["texts"])
    return " ".join((*[str(value) for value in raw["events"]], str(raw["transcript"]))).strip()


def _evidence_payload(
    action: str,
    video_id: str,
    window: Mapping[str, Any],
    raw: Mapping[str, Any],
    embedding: tuple[float, ...] | None,
) -> dict[str, Any]:
    text = _action_text(action, raw)
    direction, cues = smoke_evidence_direction(text)
    ordinal = int(window["ordinal"])
    atom_id = f"mvp-real-atom-{video_id.removeprefix('mvp-video-')}-{ordinal:04d}-{action.casefold()}"
    interval = {
        "end_us": int(window.get("evidence_end_us", window["end_us"])),
        "start_us": int(window.get("evidence_start_us", window["start_us"])),
    }
    atoms = []
    risk_atom_ids = []
    if direction != 0.0:
        risk_atom_ids.append(atom_id)
        atoms.append(
            {
                "atom_id": atom_id,
                "direction": direction,
                "fact_slot": ["scene", "risk", "window", action.casefold()],
                "interpretation_trace": "smoke-only normal cue refutes the same suspicious explanation"
                if direction < 0.0
                else None,
                "interval": interval,
                "q_in": float(raw["confidence"]),
                "q_src": 1.0,
                "quality_policy": "MEASURED",
                "role": "RISK",
                "source_family": _ACTION_FAMILY[action],
                "status": "VALID",
                "validity_gate": 1,
            }
        )
    facts = tuple(_tokens(text)[:16])
    return {
        "atoms": atoms,
        "channel": _ACTION_CHANNEL[action],
        "direction": direction,
        "embedding": None if embedding is None else list(embedding),
        "fact_tokens": list(facts),
        "family": _ACTION_FAMILY[action],
        "observation_id": f"obs-{window['window_id']}-{action.casefold()}",
        "observed_intervals": [interval],
        "q_in": float(raw["confidence"]),
        "q_src": 1.0,
        "risk_atom_ids": risk_atom_ids,
        "smoke_cues": list(cues),
        "smoke_mapper_identity": SMOKE_MAPPER_IDENTITY,
        "source": f"real-{action.casefold()}-precomputed",
        "status": "SUCCEEDED",
        "temporal_facts": [
            {"end_us": interval["end_us"], "fact_id": fact, "start_us": interval["start_us"]}
            for fact in facts
        ],
    }


def _artifact_record(artifact_id: str, receipt: Any, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "artifact_id": artifact_id,
        "byte_length": receipt.byte_length,
        "payload_hash": receipt.payload_hash,
        "relative_ref": receipt.relative_ref,
        "sha256": receipt.file_hash,
    }


def precompute_asset_bundle(
    *,
    bundle_id: str,
    source_manifest_path: Path,
    asset_root: Path,
    bundle_root: Path,
    model_config: MvpRealModelConfig,
    backends: MvpRealBackends | None = None,
) -> MvpAssetBundleReceipt:
    validate_attempt_id(bundle_id)
    status = inspect_real_assets(source_manifest_path, asset_root, model_config)
    if status["status_code"] != "ASSET_READY":
        raise fatal("ASSET_NOT_RUN", "required real assets are unavailable")
    validate_path_identity(bundle_root)
    if bundle_root.exists() or bundle_root.is_symlink():
        raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "asset bundle root must be fresh")
    source = load_asset_source_manifest(source_manifest_path, asset_root)
    v1 = source["manifest_type"] == SOURCE_MANIFEST_TYPE_V1
    adapter_identity = ADAPTER_IDENTITY_V1 if v1 else ADAPTER_IDENTITY_V0
    precomputed_manifest_type = PRECOMPUTED_MANIFEST_TYPE_V1 if v1 else PRECOMPUTED_MANIFEST_TYPE_V0
    source_assets = _source_inventory(source, asset_root)
    model_files = tuple(
        record
        for model_id in _MODEL_FIELDS
        for record in _inventory_tree(getattr(model_config, model_id), model_id)
    )
    backend = LocalRealBackends(model_config, asset_root) if backends is None else backends

    planned = {"input": "mvp_precomputed_input.json", "bundle": "mvp_asset_bundle_manifest.json"}
    for video in source["videos"]:
        for window in video["windows"]:
            prefix = f"{video['video_id']}/{window['window_id']}"
            for action in ("caption", "ocr", "audio", "embedding"):
                planned[f"raw:{prefix}:{action}"] = f"raw/{prefix}/{action}.json"
            for action in ("vlm", "ocr", "audio"):
                planned[f"evidence:{prefix}:{action}"] = f"evidence/{prefix}/{action}.json"
    publisher = MvpImmutablePublisher(bundle_root, planned)
    raw_records: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    prepared_videos: list[dict[str, Any]] = []
    try:
        for video in source["videos"]:
            prepared_windows: list[dict[str, Any]] = []
            for window in video["windows"]:
                backend_window = _backend_window(video, window, asset_root)
                prefix = f"{video['video_id']}/{window['window_id']}"
                try:
                    caption_raw = _normalize_raw("CAPTION", backend.caption(backend_window))
                    ocr_raw = _normalize_raw("OCR", backend.ocr(backend_window))
                    audio_raw = _normalize_raw("AUDIO", backend.audio(backend_window))
                    embedding_text = str(caption_raw["text"]).strip()
                    embedding_raw = _normalize_raw("EMBEDDING", backend.embedding(embedding_text, backend_window))
                except MvpFailure:
                    raise
                except Exception as exc:
                    raise _safe_failure("ASSET_NOT_RUN", "real backend execution failed", exc) from exc
                normalized_raw = {
                    "caption": caption_raw,
                    "ocr": ocr_raw,
                    "audio": audio_raw,
                    "embedding": embedding_raw,
                }
                raw_by_action: dict[str, dict[str, Any]] = {}
                for action, raw in normalized_raw.items():
                    target_id = f"raw:{prefix}:{action}"
                    receipt = publisher.publish(target_id, dumps(raw), payload_hash(raw))
                    record = _artifact_record(f"raw:{prefix}:{action}", receipt, action.upper())
                    raw_records.append(record)
                    raw_by_action[action] = record
                vector = tuple(float(value) for value in embedding_raw["vector"])
                evidence_payloads = {
                    "VLM": _evidence_payload("VLM", str(video["video_id"]), window, caption_raw, vector),
                    "OCR": _evidence_payload("OCR", str(video["video_id"]), window, ocr_raw, None),
                    "AUDIO": _evidence_payload("AUDIO", str(video["video_id"]), window, audio_raw, None),
                }
                window_evidence: dict[str, dict[str, Any]] = {}
                for action, evidence in evidence_payloads.items():
                    target_id = f"evidence:{prefix}:{action.casefold()}"
                    parents = (
                        raw_by_action["caption"]["payload_hash"],
                        raw_by_action["embedding"]["payload_hash"],
                    ) if action == "VLM" else (raw_by_action[action.casefold()]["payload_hash"],)
                    receipt = publisher.publish(
                        target_id,
                        dumps(evidence),
                        payload_hash(evidence),
                        parent_payload_hashes=parents,
                    )
                    record = _artifact_record(f"evidence:{prefix}:{action.casefold()}", receipt, action)
                    evidence_records.append(record)
                    window_evidence[action] = {
                        "byte_length": receipt.byte_length,
                        "payload_hash": receipt.payload_hash,
                        "relative_ref": receipt.relative_ref,
                        "sha256": receipt.file_hash,
                    }
                prepared_window = {
                    "delta_us": int(window["delta_us"]),
                    "end_us": int(window["end_us"]),
                    "evidence_artifacts": window_evidence,
                    "ordinal": int(window["ordinal"]),
                    "start_us": int(window["start_us"]),
                    "window_id": str(window["window_id"]),
                }
                if v1:
                    prepared_window.update(
                        {
                            "end_frame": int(window["end_frame"]),
                            "evidence_end_frame": int(window["evidence_end_frame"]),
                            "evidence_end_us": int(window["evidence_end_us"]),
                            "evidence_start_frame": int(window["evidence_start_frame"]),
                            "evidence_start_us": int(window["evidence_start_us"]),
                            "start_frame": int(window["start_frame"]),
                        }
                    )
                prepared_windows.append(prepared_window)
            prepared_video = {"video_id": str(video["video_id"]), "windows": prepared_windows}
            if v1:
                prepared_video["frame_count"] = int(video["frame_count"])
            prepared_videos.append(prepared_video)
    finally:
        backend.close()

    prepared = {
        "adapter_identity": adapter_identity,
        "bundle_id": bundle_id,
        "bundle_manifest_ref": "mvp_asset_bundle_manifest.json",
        "dataset_id": str(source["dataset_id"]),
        "manifest_type": precomputed_manifest_type,
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "source_manifest_sha256": file_sha256(source_manifest_path),
        "videos": prepared_videos,
    }
    if v1:
        prepared.update(
            {
                "decision_point_count": sum(len(video["windows"]) for video in source["videos"]),
                "decision_stride_frames": int(source["decision_stride_frames"]),
                "evidence_context_frames": int(source["evidence_context_frames"]),
                "frame_rate": dict(source["frame_rate"]),
                "temporal_protocol": str(source["temporal_protocol"]),
            }
        )
    else:
        prepared["static_max_case_count"] = sum(len(video["windows"]) for video in source["videos"])
    input_receipt = publisher.publish(
        "input",
        dumps(prepared),
        payload_hash(prepared),
        parent_payload_hashes=tuple(record["payload_hash"] for record in evidence_records),
    )
    config_payload = {
        "audio_compute_type": model_config.audio_compute_type,
        "caption_fps": model_config.caption_fps,
        "caption_max_frames": model_config.caption_max_frames,
        "caption_max_new_tokens": model_config.caption_max_new_tokens,
        "caption_temperature": model_config.caption_temperature,
        "gpu_device": model_config.gpu_device,
        "ocr_languages": list(model_config.ocr_languages),
    }
    bundle_manifest = {
        "adapter_identity": adapter_identity,
        "backend_identity": str(backend.identity),
        "bundle_id": bundle_id,
        "evidence_artifacts": evidence_records,
        "input_manifest": {
            "byte_length": input_receipt.byte_length,
            "payload_hash": input_receipt.payload_hash,
            "relative_ref": input_receipt.relative_ref,
            "sha256": input_receipt.file_hash,
        },
        "model_config": config_payload,
        "model_files": list(model_files),
        "model_identity_payload_hash": payload_hash({"files": model_files}),
        "raw_output_artifacts": raw_records,
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "runtime_profile": RUNTIME_PROFILE,
        "smoke_mapper_identity": SMOKE_MAPPER_IDENTITY,
        "source_assets": list(source_assets),
        "source_manifest_sha256": file_sha256(source_manifest_path),
    }
    bundle_parents = (
        file_sha256(source_manifest_path),
        input_receipt.payload_hash,
        *(record["sha256"] for record in model_files),
        *(record["sha256"] for record in source_assets),
        *(record["payload_hash"] for record in raw_records),
        *(record["payload_hash"] for record in evidence_records),
    )
    bundle_receipt = publisher.publish(
        "bundle",
        dumps(bundle_manifest),
        payload_hash(bundle_manifest),
        parent_payload_hashes=bundle_parents,
    )
    return MvpAssetBundleReceipt(
        bundle_id=bundle_id,
        bundle_manifest_path=bundle_root / bundle_receipt.relative_ref,
        bundle_manifest_sha256=bundle_receipt.file_hash,
        input_manifest_path=bundle_root / input_receipt.relative_ref,
        input_manifest_sha256=input_receipt.file_hash,
    )


class MvpPrecomputedEvidenceResolver:
    """Hash-bound action capability; evidence JSON is decoded only when B3 requests it."""

    def __init__(self, bundle_root: Path) -> None:
        validate_path_identity(bundle_root)
        if not bundle_root.is_dir() or bundle_root.is_symlink():
            raise fatal("MVP_PATH_ESCAPE", "precomputed evidence root is invalid")
        self.bundle_root = bundle_root
        self._decoded: list[tuple[str, str]] = []

    @property
    def decoded_actions(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._decoded)

    def load(self, video_id: str, window: Mapping[str, Any], action: str) -> dict[str, Any]:
        if action not in {"VLM", "OCR", "AUDIO"}:
            raise fatal("MVP_PATH_ESCAPE", "evidence action is outside the closed registry")
        window_id = str(window["window_id"])
        key = (window_id, action)
        if key in self._decoded:
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "evidence action was decoded more than once")
        try:
            entry = window["evidence_artifacts"][action]
            path = resolve_relative(self.bundle_root, str(entry["relative_ref"]))
            raw_bytes = path.read_bytes()
            digest = file_sha256(path)
            if (
                path.stat().st_size != int(entry["byte_length"])
                or digest != str(entry["sha256"])
                or digest != str(entry["payload_hash"])
            ):
                raise ValueError("evidence binding mismatch")
            raw = loads(raw_bytes)
            if not isinstance(raw, dict):
                raise ValueError("evidence object required")
            if raw.get("observation_id") != f"obs-{window_id}-{action.casefold()}":
                raise ValueError("evidence observation identity mismatch")
            if str(raw.get("channel")) != _ACTION_CHANNEL[action]:
                raise ValueError("evidence channel mismatch")
            validate_inference_boundary(raw)
        except MvpFailure:
            raise
        except Exception as exc:
            raise _safe_failure("MVP_FREEZE_INVALID", "requested evidence failed hash verification", exc) from exc
        self._decoded.append(key)
        return raw


def load_precomputed_input(
    input_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], MvpPrecomputedEvidenceResolver]:
    """Verify the complete frozen bundle before an attempt root or Memory namespace exists."""

    validate_path_identity(input_manifest_path)
    if not input_manifest_path.is_file() or input_manifest_path.is_symlink():
        raise fatal("ASSET_NOT_RUN", "precomputed input manifest is unavailable")
    prepared = _read_object(input_manifest_path, "MVP_FREEZE_INVALID")
    validate_inference_boundary(prepared)
    manifest_type = prepared.get("manifest_type")
    v1 = manifest_type == PRECOMPUTED_MANIFEST_TYPE_V1
    required = {
        "adapter_identity",
        "bundle_id",
        "bundle_manifest_ref",
        "dataset_id",
        "manifest_type",
        "research_claim_status",
        "runtime_profile",
        "source_manifest_sha256",
        "videos",
    }
    if v1:
        required.update(
            {
                "decision_point_count",
                "decision_stride_frames",
                "evidence_context_frames",
                "frame_rate",
                "temporal_protocol",
            }
        )
        expected_adapter_identity = ADAPTER_IDENTITY_V1
    else:
        required.add("static_max_case_count")
        expected_adapter_identity = ADAPTER_IDENTITY_V0
    if set(prepared) != required:
        raise fatal("MVP_FREEZE_INVALID", "precomputed input fields are not closed")
    if (
        manifest_type not in {PRECOMPUTED_MANIFEST_TYPE_V0, PRECOMPUTED_MANIFEST_TYPE_V1}
        or prepared["adapter_identity"] != expected_adapter_identity
        or prepared["runtime_profile"] != RUNTIME_PROFILE
        or prepared["research_claim_status"] != RESEARCH_CLAIM_STATUS
    ):
        raise fatal("MVP_FREEZE_INVALID", "precomputed input identity is invalid")
    bundle_root = input_manifest_path.parent
    bundle_path = resolve_relative(bundle_root, str(prepared["bundle_manifest_ref"]))
    bundle = _read_object(bundle_path, "MVP_FREEZE_INVALID")
    if bundle.get("bundle_id") != prepared["bundle_id"] or bundle.get("adapter_identity") != expected_adapter_identity:
        raise fatal("MVP_FREEZE_INVALID", "asset bundle identity is invalid")
    input_entry = bundle.get("input_manifest")
    if not isinstance(input_entry, dict) or (
        input_entry.get("relative_ref") != input_manifest_path.name
        or input_entry.get("sha256") != file_sha256(input_manifest_path)
        or input_entry.get("byte_length") != input_manifest_path.stat().st_size
        or input_entry.get("payload_hash") != payload_hash(prepared)
    ):
        raise fatal("MVP_FREEZE_INVALID", "asset bundle does not bind the input manifest")
    all_records = (*bundle.get("raw_output_artifacts", ()), *bundle.get("evidence_artifacts", ()))
    for record in all_records:
        if not isinstance(record, dict):
            raise fatal("MVP_FREEZE_INVALID", "asset artifact registry is invalid")
        path = resolve_relative(bundle_root, str(record["relative_ref"]))
        try:
            digest = file_sha256(path)
            if (
                path.stat().st_size != int(record["byte_length"])
                or digest != str(record["sha256"])
                or digest != str(record["payload_hash"])
            ):
                raise ValueError("artifact mismatch")
        except Exception as exc:
            raise _safe_failure("MVP_FREEZE_INVALID", "asset artifact hash verification failed", exc) from exc

    materialized = {key: value for key, value in prepared.items() if key != "videos"}
    videos: list[dict[str, Any]] = []
    decision_point_count = 0
    for video in prepared["videos"]:
        video_id = str(video["video_id"])
        frame_count = int(video["frame_count"]) if v1 else None
        if v1 and frame_count <= 0:
            raise fatal("MVP_TIME_INVALID", "precomputed frame count is invalid")
        windows: list[dict[str, Any]] = []
        for expected_ordinal, window in enumerate(video["windows"]):
            if int(window["ordinal"]) != expected_ordinal:
                raise fatal("MVP_WINDOW_ORDER_VIOLATION", "precomputed windows are not ordered")
            for action in ("VLM", "OCR", "AUDIO"):
                entry = window["evidence_artifacts"][action]
                path = resolve_relative(bundle_root, str(entry["relative_ref"]))
                if (
                    file_sha256(path) != str(entry["sha256"])
                    or path.stat().st_size != int(entry["byte_length"])
                    or str(entry["sha256"]) != str(entry["payload_hash"])
                ):
                    raise fatal("MVP_FREEZE_INVALID", "window evidence binding is invalid")
            materialized_window = {
                "delta_us": int(window["delta_us"]),
                "end_us": int(window["end_us"]),
                "evidence_artifacts": dict(window["evidence_artifacts"]),
                "ordinal": int(window["ordinal"]),
                "start_us": int(window["start_us"]),
                "window_id": str(window["window_id"]),
            }
            if v1:
                materialized_window.update(
                    {
                        "end_frame": int(window["end_frame"]),
                        "evidence_end_frame": int(window["evidence_end_frame"]),
                        "evidence_end_us": int(window["evidence_end_us"]),
                        "evidence_start_frame": int(window["evidence_start_frame"]),
                        "evidence_start_us": int(window["evidence_start_us"]),
                        "frame_count": frame_count,
                        "frame_interval": int(prepared["decision_stride_frames"]),
                        "start_frame": int(window["start_frame"]),
                    }
                )
            windows.append(materialized_window)
            decision_point_count += 1
        materialized_video = {"video_id": video_id, "windows": windows}
        if v1:
            materialized_video["frame_count"] = frame_count
        videos.append(materialized_video)
    if v1 and decision_point_count != int(prepared["decision_point_count"]):
        raise fatal("MVP_WINDOW_ORDER_VIOLATION", "precomputed decision point count is invalid")
    materialized["videos"] = videos
    materialized["asset_bundle_manifest_sha256"] = file_sha256(bundle_path)
    materialized["asset_bundle_manifest"] = bundle
    return materialized, bundle, MvpPrecomputedEvidenceResolver(bundle_root)


class LocalRealBackends:
    """Heavy Legacy-backend containment; imports occur only after explicit device binding."""

    identity = "LOCAL_CAPTION_OCR_AUDIO_EMBEDDING_BACKENDS_MVP_V0"

    def __init__(self, config: MvpRealModelConfig, asset_root: Path) -> None:
        self.config = config
        self.asset_root = asset_root
        requested = config.gpu_device.strip()
        if requested.casefold() != "cpu":
            existing = os.environ.get("CUDA_VISIBLE_DEVICES")
            if existing is not None and existing != requested:
                raise fatal("ASSET_NOT_RUN", "CUDA device binding conflicts with the requested model profile")
            os.environ["CUDA_VISIBLE_DEVICES"] = requested
        self._caption_backend: Any = None
        self._ocr_reader: Any = None
        self._audio_model: Any = None
        self._embedding_builder: Any = None

    def _window_input(self, window: Mapping[str, Any]) -> Any:
        from src.core.schemas import TimeSpan, WindowInput

        return WindowInput(
            video_id=str(window["video_id"]),
            video_path=str(window["video_path"]),
            window_id=str(window["window_id"]),
            time_span=TimeSpan(
                start_frame=int(window["start_frame"]),
                end_frame=int(window["end_frame"]),
                start_time=float(int(window["start_us"]) / 1_000_000),
                end_time=float(int(window["end_us"]) / 1_000_000),
            ),
            frame_indices=list(range(int(window["start_frame"]), int(window["end_frame"]) + 1)),
            audio_path=str(window["audio_path"]),
            frame_paths=[str(value) for value in window["frame_paths"]],
        )

    def caption(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._caption_backend is None:
            from src.tools.vlm_tool import VideoLLaMABackend

            device = "cpu" if self.config.gpu_device.casefold() == "cpu" else "cuda:0"
            self._caption_backend = VideoLLaMABackend(
                video_root=self.asset_root,
                model_path=self.config.caption_model,
                runtime_device=device,
                max_frames=self.config.caption_max_frames,
                fps=self.config.caption_fps,
                max_new_tokens=self.config.caption_max_new_tokens,
                temperature=self.config.caption_temperature,
            )
        result = self._caption_backend.describe(self._window_input(window))
        return {
            "backend_name": str(result.get("backend_name", self._caption_backend.name)),
            "confidence": float(result.get("confidence", 0.0)),
            "text": str(result.get("vision_caption", "")),
        }

    def ocr(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._ocr_reader is None:
            import easyocr

            self._ocr_reader = easyocr.Reader(
                list(self.config.ocr_languages),
                gpu=self.config.gpu_device.casefold() != "cpu",
                model_storage_directory=str(self.config.ocr_model),
                user_network_directory=str(self.config.ocr_model),
                download_enabled=False,
            )
        texts: list[str] = []
        confidences: list[float] = []
        for frame_path in window["frame_paths"]:
            for _box, text, confidence in self._ocr_reader.readtext(str(frame_path), detail=1):
                if str(text).strip():
                    texts.append(str(text).strip())
                    confidences.append(float(confidence))
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return {"backend_name": "easyocr-local", "confidence": confidence, "texts": texts}

    def audio(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._audio_model is None:
            from faster_whisper import WhisperModel

            device = "cpu" if self.config.gpu_device.casefold() == "cpu" else "cuda"
            compute_type = "int8" if device == "cpu" else self.config.audio_compute_type
            self._audio_model = WhisperModel(str(self.config.audio_model), device=device, compute_type=compute_type)
        segments, _info = self._audio_model.transcribe(str(window["audio_path"]), beam_size=1)
        transcript = " ".join(str(segment.text).strip() for segment in segments if str(segment.text).strip())
        lowered = transcript.casefold()
        events = ["distress_audio"] if any(cue in lowered for cue in ("help", "scream", "alarm")) else []
        return {
            "backend_name": "faster-whisper-local",
            "confidence": 0.7 if transcript else 0.0,
            "events": events,
            "transcript": transcript,
        }

    def embedding(self, text: str, window: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._embedding_builder is None:
            from src.memory.embedding_builder import EmbeddingBuilder

            device = "cpu" if self.config.gpu_device.casefold() == "cpu" else "cuda:0"
            self._embedding_builder = EmbeddingBuilder(model_name=str(self.config.embedding_model), device=device)
            if self._embedding_builder._get_model() is None:
                raise fatal("ASSET_NOT_RUN", "real embedding model failed to load; fallback is forbidden")
        vector = self._embedding_builder.embed_texts((text,))[0]
        if self._embedding_builder._model is None or self._embedding_builder._load_error is not None:
            raise fatal("ASSET_NOT_RUN", "real embedding backend attempted a fallback")
        return {"backend_name": "sentence-transformers-local", "fallback_used": False, "vector": vector}

    def close(self) -> None:
        if self._caption_backend is not None:
            self._caption_backend.close()
        self._caption_backend = None
        self._ocr_reader = None
        self._audio_model = None
        self._embedding_builder = None
