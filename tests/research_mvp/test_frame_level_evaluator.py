from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter1d

from src.research_mvp.evaluator.metrics import (
    DIRECT_B4_POSTPROCESS,
    GAUSSIAN_POSTPROCESS,
    evaluate_frame_predictions,
    frame_labels,
    postprocess_for_config,
    project_video_predictions,
    temporal_protocol_for_config,
)
from src.research_mvp.evaluator.cli import main as evaluator_cli_main
from src.research_mvp.media import CAUSAL_PROTOCOL, OFFLINE_PROTOCOL, STREAM_CAUSAL_PROTOCOL
from src.research_mvp.evaluator.targets import build_ucf_frame_target_manifest


def _predictions(scores: tuple[float, ...], frame_count: int = 33) -> tuple[dict[str, object], ...]:
    records = []
    for ordinal, score in enumerate(scores):
        start = ordinal * 16
        records.append(
            {
                "end_frame": min(start + 15, frame_count - 1),
                "frame_count": frame_count,
                "frame_interval": 16,
                "prediction": score,
                "prediction_payload_hash": f"{ordinal + 1:064x}",
                "start_frame": start,
                "video_id": "mvp-video-example",
                "window_id": f"mvp-video-example-window-{ordinal:04d}",
                "window_ordinal": ordinal,
            }
        )
    return tuple(records)


def test_direct_b4_projection_assigns_one_score_to_every_original_frame() -> None:
    projected = project_video_predictions(
        _predictions((0.1, 0.2, 0.3)),
        frame_count=33,
        frame_interval=16,
        gaussian_sigma=None,
    )

    assert projected == (0.1,) * 16 + (0.2,) * 16 + (0.3,)


def test_original_style_projection_applies_gaussian_before_frame_repeat() -> None:
    projected = project_video_predictions(
        _predictions((0.1, 0.2, 0.3)),
        frame_count=33,
        frame_interval=16,
        gaussian_sigma=10.0,
    )
    expected = tuple(np.repeat(gaussian_filter1d(np.asarray([0.1, 0.2, 0.3]), sigma=10), 16)[:33])

    assert projected == pytest.approx(expected)


@pytest.mark.parametrize("config_id", ("O0", "O1", "I0", "I1", "I2"))
def test_baseline_and_pre_b4_configs_register_author_gaussian(config_id: str) -> None:
    assert postprocess_for_config(config_id) == (GAUSSIAN_POSTPROCESS, 10.0)


@pytest.mark.parametrize("config_id", ("I3", "I4", "C0", "C1", "S0"))
def test_b4_configs_register_direct_predictions(config_id: str) -> None:
    assert postprocess_for_config(config_id) == (DIRECT_B4_POSTPROCESS, None)


@pytest.mark.parametrize("config_id", ("O0", "O1", "I0", "I1", "I2", "I3", "I4"))
def test_offline_configs_register_offline_temporal_protocol(config_id: str) -> None:
    assert temporal_protocol_for_config(config_id) == OFFLINE_PROTOCOL


@pytest.mark.parametrize("config_id", ("C0", "C1"))
def test_independent_causal_configs_register_causal_protocol(config_id: str) -> None:
    assert temporal_protocol_for_config(config_id) == CAUSAL_PROTOCOL


def test_stream_config_registers_stream_causal_protocol() -> None:
    assert temporal_protocol_for_config("S0") == STREAM_CAUSAL_PROTOCOL


def test_frame_labels_use_inclusive_anomaly_intervals() -> None:
    assert frame_labels(8, ((2, 4), (7, 7)), normal_label=0) == (0, 0, 1, 1, 1, 0, 0, 1)


def test_frame_evaluator_flattens_formal_targets_and_reports_protocol() -> None:
    target_manifest = {
        "dataset_id": "mini",
        "experiment_config_id": "I3",
        "frame_interval": 16,
        "manifest_type": "MVP_FRAME_TARGETS_V1",
        "normal_label": 0,
        "postprocess_identity": DIRECT_B4_POSTPROCESS,
        "temporal_protocol": OFFLINE_PROTOCOL,
        "videos": [
            {
                "anomaly_intervals": [{"end_frame": 32, "start_frame": 16}],
                "frame_count": 33,
                "video_id": "mvp-video-example",
            }
        ],
    }

    result = evaluate_frame_predictions(_predictions((0.1, 0.8, 0.9)), target_manifest)

    assert result["frame_count"] == 33
    assert result["video_count"] == 1
    assert result["postprocess_identity"] == DIRECT_B4_POSTPROCESS
    assert result["metrics"]["roc_auc"]["status"] == "DEFINED"
    assert result["metrics"]["roc_auc"]["value"] == pytest.approx(1.0)


def test_frame_projection_rejects_a_missing_decision_point() -> None:
    with pytest.raises(ValueError, match="prediction grid"):
        project_video_predictions(
            _predictions((0.1, 0.2)),
            frame_count=33,
            frame_interval=16,
            gaussian_sigma=None,
        )


def test_ucf_target_builder_keeps_annotations_outside_source_manifest(tmp_path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text(
        """{
          "dataset_id": "mini",
          "decision_stride_frames": 16,
          "evidence_context_frames": 300,
          "frame_rate": {"denominator": 1, "numerator": 30},
          "manifest_type": "MVP_REAL_ASSET_SOURCE_V1",
          "runtime_profile": "RESEARCH_MVP",
          "temporal_protocol": "ZS-Independent-Offline",
          "videos": [
            {"frame_count": 33, "video_id": "mvp-video-abuse028-x264", "video_ref": "videos/Abuse028_x264.mp4", "windows": []},
            {"frame_count": 16, "video_id": "mvp-video-arson010-x264", "video_ref": "videos/Arson010_x264.mp4", "windows": []}
          ]
        }""",
        encoding="utf-8",
    )
    temporal_path = tmp_path / "temporal.txt"
    temporal_path.write_text(
        "Arson010_x264.mp4 0 -1 -1 -1 -1\nAbuse028_x264.mp4 0 2 4 7 7\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "targets.json"

    receipt = build_ucf_frame_target_manifest(
        source_manifest_path=source_path,
        temporal_annotation_path=temporal_path,
        output_path=output_path,
        experiment_config_id="I3",
    )

    assert receipt.video_count == 2
    target = __import__("json").loads(output_path.read_bytes())
    assert [video["video_id"] for video in target["videos"]] == [
        "mvp-video-abuse028-x264",
        "mvp-video-arson010-x264",
    ]
    assert target["videos"][0]["anomaly_intervals"] == [
        {"end_frame": 4, "start_frame": 2},
        {"end_frame": 7, "start_frame": 7},
    ]
    assert target["videos"][1]["anomaly_intervals"] == []
    assert b"anomaly_intervals" not in source_path.read_bytes()


def test_evaluator_cli_builds_frame_targets(tmp_path, capsys) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text(
        """{
          "dataset_id": "mini",
          "decision_stride_frames": 16,
          "evidence_context_frames": 300,
          "frame_rate": {"denominator": 1, "numerator": 30},
          "manifest_type": "MVP_REAL_ASSET_SOURCE_V1",
          "runtime_profile": "RESEARCH_MVP",
          "temporal_protocol": "ZS-Independent-Offline",
          "videos": [
            {"frame_count": 16, "video_id": "mvp-video-example", "video_ref": "videos/Example.mp4", "windows": []}
          ]
        }""",
        encoding="utf-8",
    )
    temporal_path = tmp_path / "temporal.txt"
    temporal_path.write_text("Example.mp4 0 2 4\n", encoding="utf-8")
    output_path = tmp_path / "targets.json"

    exit_code = evaluator_cli_main(
        [
            "build-frame-targets",
            "--source-manifest",
            str(source_path),
            "--temporal-annotations",
            str(temporal_path),
            "--output",
            str(output_path),
            "--experiment-config",
            "I3",
        ]
    )

    assert exit_code == 0
    assert output_path.is_file()
    assert __import__("json").loads(capsys.readouterr().out)["status_code"] == "FRAME_TARGETS_FROZEN"
