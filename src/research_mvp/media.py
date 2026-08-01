from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import RUNTIME_PROFILE
from .artifacts.hashes import file_sha256
from .artifacts.resolver import resolve_relative
from .codec import dumps, payload_hash
from .failures import MvpFailure, fatal
from .ids import window_semantic_id


OFFLINE_PROTOCOL = "ZS-Independent-Offline"
CAUSAL_PROTOCOL = "ZS-Independent-Causal"
STREAM_CAUSAL_PROTOCOL = "ZS-Stream-Causal"
TEMPORAL_PROTOCOLS = frozenset({OFFLINE_PROTOCOL, CAUSAL_PROTOCOL, STREAM_CAUSAL_PROTOCOL})
SOURCE_MANIFEST_TYPE = "MVP_REAL_ASSET_SOURCE_V1"


CommandRunner = Callable[[tuple[str, ...]], subprocess.CompletedProcess[bytes]]


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def frame_boundary_us(frame_index: int, fps_num: int, fps_den: int) -> int:
    """Return the nearest integer microsecond for an exact rational frame boundary."""

    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
        raise ValueError("frame_index must be a non-negative integer")
    _positive_int(fps_num, "fps_num")
    _positive_int(fps_den, "fps_den")
    numerator = frame_index * fps_den * 1_000_000
    return (numerator + fps_num // 2) // fps_num


@dataclass(frozen=True, slots=True)
class PlannedMediaWindow:
    video_id: str
    window_id: str
    ordinal: int
    start_frame: int
    end_frame: int
    start_us: int
    end_us: int
    delta_us: int
    evidence_start_frame: int
    evidence_end_frame: int
    evidence_start_us: int
    evidence_end_us: int


@dataclass(frozen=True, slots=True)
class MediaPreparationConfig:
    dataset_id: str
    temporal_protocol: str
    decision_stride_frames: int = 16
    evidence_context_frames: int = 300
    caption_fps: int = 2
    caption_max_frames: int = 10
    audio_sample_rate: int = 16_000
    ffmpeg_executable: str = "ffmpeg"
    ffprobe_executable: str = "ffprobe"

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id:
            raise ValueError("dataset_id must be non-empty")
        if self.temporal_protocol not in TEMPORAL_PROTOCOLS:
            raise ValueError("unregistered temporal protocol")
        for name in (
            "decision_stride_frames",
            "evidence_context_frames",
            "caption_fps",
            "caption_max_frames",
            "audio_sample_rate",
        ):
            _positive_int(getattr(self, name), name)
        if not self.ffmpeg_executable or not self.ffprobe_executable:
            raise ValueError("ffmpeg and ffprobe executables must be explicit")


@dataclass(frozen=True, slots=True)
class MediaPreparationReceipt:
    source_manifest_path: Path
    source_manifest_sha256: str
    cache_manifest_path: Path
    cache_hit: bool
    video_count: int
    window_count: int


def _offline_evidence_range(
    decision_start: int,
    decision_end_exclusive: int,
    frame_count: int,
    context_frames: int,
) -> tuple[int, int]:
    if frame_count <= context_frames:
        return 0, frame_count
    centered_start = (decision_start + decision_end_exclusive - context_frames) // 2
    evidence_start = min(max(centered_start, 0), frame_count - context_frames)
    return evidence_start, evidence_start + context_frames


def plan_video_windows(
    *,
    video_id: str,
    frame_count: int,
    fps_num: int,
    fps_den: int,
    temporal_protocol: str,
    decision_stride_frames: int = 16,
    evidence_context_frames: int = 300,
) -> tuple[PlannedMediaWindow, ...]:
    _positive_int(frame_count, "frame_count")
    _positive_int(fps_num, "fps_num")
    _positive_int(fps_den, "fps_den")
    _positive_int(decision_stride_frames, "decision_stride_frames")
    _positive_int(evidence_context_frames, "evidence_context_frames")
    if temporal_protocol not in TEMPORAL_PROTOCOLS:
        raise ValueError("unregistered temporal protocol")

    planned: list[PlannedMediaWindow] = []
    for ordinal, decision_start in enumerate(range(0, frame_count, decision_stride_frames)):
        decision_end_exclusive = min(decision_start + decision_stride_frames, frame_count)
        if temporal_protocol == OFFLINE_PROTOCOL:
            evidence_start, evidence_end_exclusive = _offline_evidence_range(
                decision_start,
                decision_end_exclusive,
                frame_count,
                evidence_context_frames,
            )
        else:
            evidence_end_exclusive = decision_end_exclusive
            evidence_start = max(0, evidence_end_exclusive - evidence_context_frames)

        start_us = frame_boundary_us(decision_start, fps_num, fps_den)
        end_us = frame_boundary_us(decision_end_exclusive, fps_num, fps_den)
        evidence_start_us = frame_boundary_us(evidence_start, fps_num, fps_den)
        evidence_end_us = frame_boundary_us(evidence_end_exclusive, fps_num, fps_den)
        if end_us <= start_us or evidence_end_us <= evidence_start_us:
            raise ValueError("frame rate cannot be represented as non-empty microsecond intervals")
        planned.append(
            PlannedMediaWindow(
                video_id=video_id,
                window_id=window_semantic_id(video_id, ordinal),
                ordinal=ordinal,
                start_frame=decision_start,
                end_frame=decision_end_exclusive - 1,
                start_us=start_us,
                end_us=end_us,
                delta_us=end_us - start_us,
                evidence_start_frame=evidence_start,
                evidence_end_frame=evidence_end_exclusive - 1,
                evidence_start_us=evidence_start_us,
                evidence_end_us=evidence_end_us,
            )
        )
    return tuple(planned)


def _default_command_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, capture_output=True, check=False)


def _run_checked(command: tuple[str, ...], runner: CommandRunner) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(command)
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "media command could not be started") from exc
    if result.returncode != 0:
        raise fatal("ASSET_NOT_RUN", "media command failed")
    return result


def _probe_stream(
    video_path: Path,
    selector: str,
    executable: str,
    runner: CommandRunner,
) -> Mapping[str, Any]:
    command = (
        executable,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        selector,
        "-show_entries",
        "stream=index,codec_type,nb_frames,nb_read_frames,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        str(video_path),
    )
    result = _run_checked(command, runner)
    try:
        decoded = json.loads(result.stdout)
        streams = decoded["streams"]
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
            raise ValueError("one stream required")
        return streams[0]
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "ffprobe returned invalid stream metadata") from exc


def _parse_rate(value: Any) -> tuple[int, int]:
    try:
        numerator_text, denominator_text = str(value).split("/", 1)
        numerator = int(numerator_text)
        denominator = int(denominator_text)
        _positive_int(numerator, "fps numerator")
        _positive_int(denominator, "fps denominator")
        return numerator, denominator
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "video frame rate is invalid") from exc


def _probe_video(
    video_path: Path,
    config: MediaPreparationConfig,
    runner: CommandRunner,
) -> tuple[int, int, int]:
    video = _probe_stream(video_path, "v:0", config.ffprobe_executable, runner)
    audio = _probe_stream(video_path, "a:0", config.ffprobe_executable, runner)
    if video.get("codec_type") != "video" or audio.get("codec_type") != "audio":
        raise fatal("ASSET_NOT_RUN", "main video and audio streams are required")
    raw_count = video.get("nb_frames")
    if raw_count in {None, "", "N/A"}:
        raw_count = video.get("nb_read_frames")
    try:
        frame_count = int(raw_count)
        _positive_int(frame_count, "frame_count")
    except Exception as exc:
        raise fatal("ASSET_NOT_RUN", "exact decoded frame count is unavailable") from exc
    raw_rate = video.get("avg_frame_rate")
    if raw_rate in {None, "", "0/0", "N/A"}:
        raw_rate = video.get("r_frame_rate")
    fps_num, fps_den = _parse_rate(raw_rate)
    return frame_count, fps_num, fps_den


def _relative_file(path: Path, root: Path) -> str:
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        relative = resolved_path.relative_to(resolved_root)
    except Exception as exc:
        raise fatal("MVP_PATH_ESCAPE", "media source must be a regular file inside asset_root") from exc
    if path.is_symlink() or not path.is_file():
        raise fatal("MVP_PATH_ESCAPE", "media source must be a regular file inside asset_root")
    return relative.as_posix()


def _sample_frame_indices(
    window: PlannedMediaWindow,
    *,
    fps_num: int,
    fps_den: int,
    caption_fps: int,
    caption_max_frames: int,
) -> tuple[int, ...]:
    span = window.evidence_end_frame - window.evidence_start_frame + 1
    requested = (span * caption_fps * fps_den + fps_num - 1) // fps_num
    count = min(caption_max_frames, max(1, requested), span)
    if count == 1:
        return (window.evidence_start_frame + (span - 1) // 2,)
    denominator = count - 1
    return tuple(
        window.evidence_start_frame
        + (ordinal * (span - 1) + denominator // 2) // denominator
        for ordinal in range(count)
    )


def _seconds(microseconds: int) -> str:
    return f"{microseconds / 1_000_000:.6f}"


def _config_payload(config: MediaPreparationConfig) -> dict[str, Any]:
    return {
        "audio_codec": "pcm_s16le",
        "audio_sample_rate": config.audio_sample_rate,
        "audio_channels": 1,
        "caption_fps": config.caption_fps,
        "caption_max_frames": config.caption_max_frames,
        "dataset_id": config.dataset_id,
        "decision_stride_frames": config.decision_stride_frames,
        "evidence_context_frames": config.evidence_context_frames,
        "ffmpeg_executable": config.ffmpeg_executable,
        "ffprobe_executable": config.ffprobe_executable,
        "temporal_protocol": config.temporal_protocol,
    }


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        decoded = json.loads(path.read_bytes())
        return decoded if isinstance(decoded, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _cache_matches(
    cache_path: Path,
    asset_root: Path,
    source_records: Sequence[Mapping[str, Any]],
    config_fingerprint: str,
) -> dict[str, Any] | None:
    cached = _read_json_object(cache_path)
    if cached is None:
        return None
    if cached.get("config_fingerprint") != config_fingerprint or cached.get("sources") != list(source_records):
        return None
    outputs = cached.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return None
    try:
        for output in outputs:
            path = resolve_relative(asset_root, str(output["relative_ref"]))
            if not path.is_file() or path.is_symlink() or file_sha256(path) != str(output["sha256"]):
                return None
        manifest_path = resolve_relative(asset_root, str(cached["source_manifest_ref"]))
        manifest = _read_json_object(manifest_path)
        if manifest is None or file_sha256(manifest_path) != str(cached["source_manifest_sha256"]):
            return None
    except (KeyError, OSError, ValueError, MvpFailure):
        return None
    return cached


def _publish_last(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging")
    staging.write_bytes(content)
    staging.replace(path)


def prepare_media_assets(
    *,
    videos: Sequence[tuple[str, Path]],
    asset_root: Path,
    source_manifest_path: Path,
    config: MediaPreparationConfig,
    command_runner: CommandRunner = _default_command_runner,
) -> MediaPreparationReceipt:
    if not videos:
        raise ValueError("at least one video is required")
    asset_root.mkdir(parents=True, exist_ok=True)
    try:
        source_manifest_ref = source_manifest_path.resolve().relative_to(asset_root.resolve()).as_posix()
    except ValueError as exc:
        raise fatal("MVP_PATH_ESCAPE", "source manifest must be inside asset_root") from exc

    seen_ids: set[str] = set()
    source_records: list[dict[str, Any]] = []
    ordered_videos: list[tuple[str, Path, str]] = []
    for video_id, video_path in videos:
        window_semantic_id(video_id, 0)
        if video_id in seen_ids:
            raise ValueError("video identities must be unique")
        seen_ids.add(video_id)
        video_ref = _relative_file(video_path, asset_root)
        source_records.append(
            {"relative_ref": video_ref, "sha256": file_sha256(video_path), "video_id": video_id}
        )
        ordered_videos.append((video_id, video_path, video_ref))

    config_payload = _config_payload(config)
    config_fingerprint = payload_hash(config_payload)
    cache_path = (
        asset_root
        / ".asset_status"
        / "media"
        / config.dataset_id
        / f"{config.temporal_protocol.casefold().replace('-', '_')}.json"
    )
    cached = _cache_matches(cache_path, asset_root, source_records, config_fingerprint)
    if cached is not None:
        manifest_path = asset_root / source_manifest_ref
        manifest = _read_json_object(manifest_path)
        assert manifest is not None
        return MediaPreparationReceipt(
            source_manifest_path=manifest_path,
            source_manifest_sha256=file_sha256(manifest_path),
            cache_manifest_path=cache_path,
            cache_hit=True,
            video_count=len(manifest["videos"]),
            window_count=sum(len(video["windows"]) for video in manifest["videos"]),
        )

    manifest_videos: list[dict[str, Any]] = []
    output_paths: list[Path] = []
    common_rate: tuple[int, int] | None = None
    for video_id, video_path, video_ref in ordered_videos:
        frame_count, fps_num, fps_den = _probe_video(video_path, config, command_runner)
        if common_rate is None:
            common_rate = (fps_num, fps_den)
        elif common_rate != (fps_num, fps_den):
            raise fatal("MVP_TIME_INVALID", "all videos in one source manifest must share one frame rate")
        plan = plan_video_windows(
            video_id=video_id,
            frame_count=frame_count,
            fps_num=fps_num,
            fps_den=fps_den,
            temporal_protocol=config.temporal_protocol,
            decision_stride_frames=config.decision_stride_frames,
            evidence_context_frames=config.evidence_context_frames,
        )
        samples_by_window = {
            window.window_id: _sample_frame_indices(
                window,
                fps_num=fps_num,
                fps_den=fps_den,
                caption_fps=config.caption_fps,
                caption_max_frames=config.caption_max_frames,
            )
            for window in plan
        }
        unique_samples = tuple(sorted({index for values in samples_by_window.values() for index in values}))
        frame_dir = asset_root / "frames" / video_id
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_pattern = frame_dir / "%06d.jpg"
        select_filter = "select=" + "+".join(f"eq(n\\,{index})" for index in unique_samples)
        _run_checked(
            (
                config.ffmpeg_executable,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-vf",
                select_filter,
                "-fps_mode",
                "passthrough",
                "-start_number",
                "0",
                "-q:v",
                "2",
                str(frame_pattern),
            ),
            command_runner,
        )
        sample_refs: dict[int, str] = {}
        for output_ordinal, frame_index in enumerate(unique_samples):
            frame_path = frame_dir / f"{output_ordinal:06d}.jpg"
            if not frame_path.is_file() or frame_path.is_symlink():
                raise fatal("ASSET_NOT_RUN", "ffmpeg did not publish every requested evidence frame")
            output_paths.append(frame_path)
            sample_refs[frame_index] = frame_path.relative_to(asset_root).as_posix()

        windows: list[dict[str, Any]] = []
        for window in plan:
            audio_path = asset_root / "audio" / video_id / f"{window.window_id}.wav"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            _run_checked(
                (
                    config.ffmpeg_executable,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(video_path),
                    "-ss",
                    _seconds(window.evidence_start_us),
                    "-t",
                    _seconds(window.evidence_end_us - window.evidence_start_us),
                    "-map",
                    "0:a:0",
                    "-ac",
                    "1",
                    "-ar",
                    str(config.audio_sample_rate),
                    "-c:a",
                    "pcm_s16le",
                    str(audio_path),
                ),
                command_runner,
            )
            if not audio_path.is_file() or audio_path.is_symlink():
                raise fatal("ASSET_NOT_RUN", "ffmpeg did not publish the requested evidence audio")
            output_paths.append(audio_path)
            windows.append(
                {
                    "audio_ref": audio_path.relative_to(asset_root).as_posix(),
                    "delta_us": window.delta_us,
                    "end_frame": window.end_frame,
                    "end_us": window.end_us,
                    "evidence_end_frame": window.evidence_end_frame,
                    "evidence_end_us": window.evidence_end_us,
                    "evidence_start_frame": window.evidence_start_frame,
                    "evidence_start_us": window.evidence_start_us,
                    "frame_refs": [sample_refs[index] for index in samples_by_window[window.window_id]],
                    "ordinal": window.ordinal,
                    "start_frame": window.start_frame,
                    "start_us": window.start_us,
                    "window_id": window.window_id,
                }
            )
        manifest_videos.append(
            {
                "frame_count": frame_count,
                "video_id": video_id,
                "video_ref": video_ref,
                "windows": windows,
            }
        )

    assert common_rate is not None
    source_manifest = {
        "dataset_id": config.dataset_id,
        "decision_stride_frames": config.decision_stride_frames,
        "evidence_context_frames": config.evidence_context_frames,
        "frame_rate": {"denominator": common_rate[1], "numerator": common_rate[0]},
        "manifest_type": SOURCE_MANIFEST_TYPE,
        "runtime_profile": RUNTIME_PROFILE,
        "temporal_protocol": config.temporal_protocol,
        "videos": manifest_videos,
    }
    _publish_last(source_manifest_path, dumps(source_manifest))
    output_paths.append(source_manifest_path)
    outputs = [
        {
            "relative_ref": path.relative_to(asset_root).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in sorted(set(output_paths), key=lambda value: value.as_posix().encode("utf-8"))
    ]
    cache_payload = {
        "config": config_payload,
        "config_fingerprint": config_fingerprint,
        "outputs": outputs,
        "source_manifest_ref": source_manifest_ref,
        "source_manifest_sha256": file_sha256(source_manifest_path),
        "sources": source_records,
    }
    _publish_last(cache_path, dumps(cache_payload))
    return MediaPreparationReceipt(
        source_manifest_path=source_manifest_path,
        source_manifest_sha256=file_sha256(source_manifest_path),
        cache_manifest_path=cache_path,
        cache_hit=False,
        video_count=len(manifest_videos),
        window_count=sum(len(video["windows"]) for video in manifest_videos),
    )
