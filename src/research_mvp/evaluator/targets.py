from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts.hashes import file_sha256
from ..codec import dumps, loads
from .metrics import FRAME_TARGET_MANIFEST_TYPE, postprocess_for_config, temporal_protocol_for_config


@dataclass(frozen=True, slots=True)
class FrameTargetManifestReceipt:
    output_path: Path
    output_sha256: str
    video_count: int
    frame_count: int


def _read_source_manifest(path: Path) -> dict[str, Any]:
    try:
        decoded = loads(path.read_bytes())
    except Exception as exc:
        raise ValueError("source manifest is unreadable") from exc
    required = {
        "dataset_id",
        "decision_stride_frames",
        "evidence_context_frames",
        "frame_rate",
        "manifest_type",
        "runtime_profile",
        "temporal_protocol",
        "videos",
    }
    if (
        not isinstance(decoded, dict)
        or set(decoded) != required
        or decoded.get("manifest_type") != "MVP_REAL_ASSET_SOURCE_V1"
        or decoded.get("runtime_profile") != "RESEARCH_MVP"
        or decoded.get("decision_stride_frames") != 16
    ):
        raise ValueError("source manifest is not a formal V1 prediction grid")
    if not isinstance(decoded["videos"], list) or not decoded["videos"]:
        raise ValueError("source manifest requires videos")
    return decoded


def _parse_ucf_temporal_annotations(path: Path) -> dict[str, tuple[tuple[int, int], ...]]:
    parsed: dict[str, tuple[tuple[int, int], ...]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("temporal annotation file is unreadable") from exc
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 3:
            raise ValueError("temporal annotation row is incomplete")
        video_name = Path(parts[0]).stem.casefold()
        if video_name in parsed:
            raise ValueError("temporal annotation video is duplicated")
        try:
            values = tuple(int(value) for value in parts[2:] if value != "-1")
        except ValueError as exc:
            raise ValueError("temporal annotation frame is invalid") from exc
        if len(values) % 2:
            raise ValueError("temporal annotation intervals are unpaired")
        parsed[video_name] = tuple(zip(values[::2], values[1::2], strict=True))
    return parsed


def _publish_last(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging")
    staging.write_bytes(content)
    staging.replace(path)


def build_ucf_frame_target_manifest(
    *,
    source_manifest_path: Path,
    temporal_annotation_path: Path,
    output_path: Path,
    experiment_config_id: str,
) -> FrameTargetManifestReceipt:
    source = _read_source_manifest(source_manifest_path)
    annotations = _parse_ucf_temporal_annotations(temporal_annotation_path)
    postprocess_identity, _sigma = postprocess_for_config(experiment_config_id)
    temporal_protocol = temporal_protocol_for_config(experiment_config_id)
    if source["temporal_protocol"] != temporal_protocol:
        raise ValueError("experiment configuration does not match source temporal protocol")
    target_videos: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()
    for video in source["videos"]:
        if not isinstance(video, dict) or set(video) != {"frame_count", "video_id", "video_ref", "windows"}:
            raise ValueError("source video fields are invalid")
        video_id = str(video["video_id"])
        if video_id in seen_video_ids:
            raise ValueError("source video identity is duplicated")
        seen_video_ids.add(video_id)
        frame_count = video["frame_count"]
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
            raise ValueError("source frame count is invalid")
        annotation_key = Path(str(video["video_ref"])).stem.casefold()
        if annotation_key not in annotations:
            raise ValueError("temporal annotations do not cover every source video")
        intervals = annotations[annotation_key]
        previous_start = -1
        serialized_intervals: list[dict[str, int]] = []
        for start_frame, end_frame in intervals:
            if (
                start_frame < previous_start
                or start_frame < 0
                or end_frame < start_frame
                or end_frame >= frame_count
            ):
                raise ValueError("temporal annotation interval is out of source frame range")
            serialized_intervals.append({"end_frame": end_frame, "start_frame": start_frame})
            previous_start = start_frame
        target_videos.append(
            {
                "anomaly_intervals": serialized_intervals,
                "frame_count": frame_count,
                "video_id": video_id,
            }
        )
    target_videos.sort(key=lambda item: str(item["video_id"]).encode("utf-8"))
    target_manifest = {
        "dataset_id": str(source["dataset_id"]),
        "experiment_config_id": experiment_config_id,
        "frame_interval": 16,
        "manifest_type": FRAME_TARGET_MANIFEST_TYPE,
        "normal_label": 0,
        "postprocess_identity": postprocess_identity,
        "temporal_protocol": temporal_protocol,
        "videos": target_videos,
    }
    _publish_last(output_path, dumps(target_manifest))
    return FrameTargetManifestReceipt(
        output_path=output_path,
        output_sha256=file_sha256(output_path),
        video_count=len(target_videos),
        frame_count=sum(int(video["frame_count"]) for video in target_videos),
    )
