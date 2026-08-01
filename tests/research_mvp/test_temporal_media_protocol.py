from __future__ import annotations

import json
import subprocess
from pathlib import Path

import src.research_mvp.cli as mvp_cli
from src.research_mvp.media import (
    CAUSAL_PROTOCOL,
    MediaPreparationConfig,
    OFFLINE_PROTOCOL,
    frame_boundary_us,
    plan_video_windows,
    prepare_media_assets,
)


MINI_VIDEO_FRAME_COUNTS = {
    "mvp-video-abuse028": 1412,
    "mvp-video-abuse030": 1544,
    "mvp-video-arrest001": 2374,
    "mvp-video-arson009": 743,
    "mvp-video-arson010": 3159,
}


def test_frame_boundaries_use_exact_rational_rounding() -> None:
    assert [frame_boundary_us(index, 30, 1) for index in (0, 16, 32, 33)] == [
        0,
        533333,
        1066667,
        1100000,
    ]


def test_prediction_grid_uses_non_overlapping_sixteen_frame_intervals() -> None:
    plan = plan_video_windows(
        video_id="mvp-video-example",
        frame_count=33,
        fps_num=30,
        fps_den=1,
        temporal_protocol=OFFLINE_PROTOCOL,
    )

    assert [(window.start_frame, window.end_frame) for window in plan] == [
        (0, 15),
        (16, 31),
        (32, 32),
    ]
    assert [window.delta_us for window in plan] == [533333, 533334, 33333]
    assert [window.ordinal for window in plan] == [0, 1, 2]


def test_offline_evidence_context_is_centered_and_edge_shifted() -> None:
    plan = plan_video_windows(
        video_id="mvp-video-example",
        frame_count=1000,
        fps_num=30,
        fps_den=1,
        temporal_protocol=OFFLINE_PROTOCOL,
    )

    first = plan[0]
    middle = plan[19]
    final = plan[-1]
    assert (first.evidence_start_frame, first.evidence_end_frame) == (0, 299)
    assert (middle.start_frame, middle.end_frame) == (304, 319)
    assert (middle.evidence_start_frame, middle.evidence_end_frame) == (162, 461)
    assert (final.start_frame, final.end_frame) == (992, 999)
    assert (final.evidence_start_frame, final.evidence_end_frame) == (700, 999)


def test_causal_evidence_context_never_reads_after_decision_interval() -> None:
    plan = plan_video_windows(
        video_id="mvp-video-example",
        frame_count=1000,
        fps_num=30,
        fps_den=1,
        temporal_protocol=CAUSAL_PROTOCOL,
    )

    first = plan[0]
    middle = plan[19]
    assert (first.evidence_start_frame, first.evidence_end_frame) == (0, 15)
    assert (middle.evidence_start_frame, middle.evidence_end_frame) == (20, 319)
    assert middle.evidence_end_us == middle.end_us


def test_five_video_mini_dataset_has_580_decision_points() -> None:
    window_count = sum(
        len(
            plan_video_windows(
                video_id=video_id,
                frame_count=frame_count,
                fps_num=30,
                fps_den=1,
                temporal_protocol=OFFLINE_PROTOCOL,
            )
        )
        for video_id, frame_count in MINI_VIDEO_FRAME_COUNTS.items()
    )

    assert window_count == 580


class FakeMediaCommands:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
        self.commands.append(command)
        if command[0] == "ffprobe":
            selector = command[command.index("-select_streams") + 1]
            if selector == "v:0":
                payload = {
                    "streams": [
                        {
                            "codec_type": "video",
                            "index": 0,
                            "nb_frames": "33",
                            "r_frame_rate": "30/1",
                        }
                    ]
                }
            else:
                payload = {"streams": [{"codec_type": "audio", "index": 1}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")

        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if "%06d" in output.name:
            selected = command[command.index("-vf") + 1].count("eq(n\\,")
            for ordinal in range(selected):
                Path(str(output).replace("%06d", f"{ordinal:06d}")).write_bytes(
                    f"frame-{ordinal}".encode()
                )
        else:
            output.write_bytes(("audio:" + " ".join(command)).encode())
        return subprocess.CompletedProcess(command, 0, b"", b"")


def _prepared_media(tmp_path: Path, runner: FakeMediaCommands):
    asset_root = tmp_path / "assets"
    video_path = asset_root / "videos" / "example.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"source-video-v1")
    receipt = prepare_media_assets(
        videos=(("mvp-video-example", video_path),),
        asset_root=asset_root,
        source_manifest_path=asset_root / "manifests" / "mini-source.json",
        config=MediaPreparationConfig(
            dataset_id="ucf-crime-mini-five",
            temporal_protocol=OFFLINE_PROTOCOL,
        ),
        command_runner=runner,
    )
    return asset_root, receipt


def test_prepare_media_builds_v1_manifest_from_evidence_context(tmp_path: Path) -> None:
    runner = FakeMediaCommands()
    asset_root, receipt = _prepared_media(tmp_path, runner)

    assert receipt.cache_hit is False
    manifest = json.loads(receipt.source_manifest_path.read_bytes())
    assert manifest["manifest_type"] == "MVP_REAL_ASSET_SOURCE_V1"
    assert manifest["temporal_protocol"] == OFFLINE_PROTOCOL
    assert manifest["frame_rate"] == {"denominator": 1, "numerator": 30}
    assert manifest["decision_stride_frames"] == 16
    assert manifest["evidence_context_frames"] == 300
    video = manifest["videos"][0]
    assert video["frame_count"] == 33
    assert len(video["windows"]) == 3
    first = video["windows"][0]
    assert (first["start_frame"], first["end_frame"]) == (0, 15)
    assert (first["evidence_start_frame"], first["evidence_end_frame"]) == (0, 32)
    assert all((asset_root / relative).is_file() for relative in first["frame_refs"])
    assert (asset_root / first["audio_ref"]).is_file()

    video_probe = next(command for command in runner.commands if command[0] == "ffprobe" and "v:0" in command)
    audio_probe = next(command for command in runner.commands if command[0] == "ffprobe" and "a:0" in command)
    frame_command = next(command for command in runner.commands if command[0] == "ffmpeg" and "-vf" in command)
    audio_command = next(command for command in runner.commands if command[0] == "ffmpeg" and "-c:a" in command)
    assert video_probe[video_probe.index("-select_streams") + 1] == "v:0"
    assert audio_probe[audio_probe.index("-select_streams") + 1] == "a:0"
    assert frame_command[frame_command.index("-map") + 1] == "0:v:0"
    assert audio_command[audio_command.index("-map") + 1] == "0:a:0"
    assert audio_command[audio_command.index("-ac") + 1] == "1"
    assert audio_command[audio_command.index("-ar") + 1] == "16000"
    assert audio_command[audio_command.index("-c:a") + 1] == "pcm_s16le"


def test_prepare_media_cache_requires_every_output_hash(tmp_path: Path) -> None:
    first_runner = FakeMediaCommands()
    asset_root, first = _prepared_media(tmp_path, first_runner)

    def forbid_commands(command: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError(f"unexpected command: {command}")

    second = prepare_media_assets(
        videos=(("mvp-video-example", asset_root / "videos" / "example.mp4"),),
        asset_root=asset_root,
        source_manifest_path=first.source_manifest_path,
        config=MediaPreparationConfig(
            dataset_id="ucf-crime-mini-five",
            temporal_protocol=OFFLINE_PROTOCOL,
        ),
        command_runner=forbid_commands,
    )
    assert second.cache_hit is True

    manifest = json.loads(first.source_manifest_path.read_bytes())
    stale_audio = asset_root / manifest["videos"][0]["windows"][0]["audio_ref"]
    stale_audio.write_bytes(b"tampered")
    rebuild_runner = FakeMediaCommands()
    rebuilt = prepare_media_assets(
        videos=(("mvp-video-example", asset_root / "videos" / "example.mp4"),),
        asset_root=asset_root,
        source_manifest_path=first.source_manifest_path,
        config=MediaPreparationConfig(
            dataset_id="ucf-crime-mini-five",
            temporal_protocol=OFFLINE_PROTOCOL,
        ),
        command_runner=rebuild_runner,
    )
    assert rebuilt.cache_hit is False
    assert any(command[0] == "ffmpeg" for command in rebuild_runner.commands)


def test_prepare_media_cache_rejects_output_refs_outside_asset_root(tmp_path: Path) -> None:
    runner = FakeMediaCommands()
    asset_root, first = _prepared_media(tmp_path, runner)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    cache = json.loads(first.cache_manifest_path.read_bytes())
    cache["outputs"][0] = {
        "relative_ref": "../outside.jpg",
        "sha256": __import__("hashlib").sha256(outside.read_bytes()).hexdigest(),
    }
    first.cache_manifest_path.write_text(json.dumps(cache), encoding="utf-8")

    rebuild_runner = FakeMediaCommands()
    rebuilt = prepare_media_assets(
        videos=(("mvp-video-example", asset_root / "videos" / "example.mp4"),),
        asset_root=asset_root,
        source_manifest_path=first.source_manifest_path,
        config=MediaPreparationConfig(
            dataset_id="ucf-crime-mini-five",
            temporal_protocol=OFFLINE_PROTOCOL,
        ),
        command_runner=rebuild_runner,
    )

    assert rebuilt.cache_hit is False
    assert any(command[0] == "ffmpeg" for command in rebuild_runner.commands)


def test_prepare_real_media_cli_discovers_stable_video_ids(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    asset_root = tmp_path / "assets"
    video_dir = asset_root / "videos"
    video_dir.mkdir(parents=True)
    for name in ("Arson010_x264.mp4", "Abuse028_x264.mp4"):
        (video_dir / name).write_bytes(name.encode())
    captured = {}

    def fake_prepare_media_assets(**kwargs):
        captured.update(kwargs)
        source_path = kwargs["source_manifest_path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"{}")
        return mvp_cli.MediaPreparationReceipt(
            source_manifest_path=source_path,
            source_manifest_sha256="a" * 64,
            cache_manifest_path=asset_root / ".asset_status" / "cache.json",
            cache_hit=False,
            video_count=2,
            window_count=287,
        )

    monkeypatch.setattr(mvp_cli, "prepare_media_assets", fake_prepare_media_assets)
    exit_code = mvp_cli.main(
        [
            "prepare-real-media",
            "--video-dir",
            str(video_dir),
            "--asset-root",
            str(asset_root),
            "--source-manifest",
            str(asset_root / "manifests" / "mini.json"),
            "--dataset-id",
            "ucf-crime-mini-five",
            "--temporal-protocol",
            OFFLINE_PROTOCOL,
        ]
    )

    assert exit_code == 0
    assert [video_id for video_id, _path in captured["videos"]] == [
        "mvp-video-abuse028-x264",
        "mvp-video-arson010-x264",
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["status_code"] == "MEDIA_ASSETS_PREPARED"
    assert output["window_count"] == 287
