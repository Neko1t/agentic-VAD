from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d
from sklearn.metrics import auc, precision_recall_curve, roc_curve

from ..ids import window_semantic_id
from ..media import CAUSAL_PROTOCOL, OFFLINE_PROTOCOL, STREAM_CAUSAL_PROTOCOL


FRAME_TARGET_MANIFEST_TYPE = "MVP_FRAME_TARGETS_V1"
GAUSSIAN_POSTPROCESS = "AUTHOR_GAUSSIAN_SIGMA_10"
DIRECT_B4_POSTPROCESS = "DIRECT_B4_NO_GAUSSIAN"
_GAUSSIAN_CONFIGS = frozenset({"O0", "O1", "I0", "I1", "I2"})
_DIRECT_CONFIGS = frozenset({"I3", "I4", "C0", "C1", "S0"})


def _undefined() -> dict[str, str]:
    return {"reason": "single_class", "status": "METRIC_UNDEFINED"}


def evaluate_binary_metrics(labels: tuple[int, ...], scores: tuple[float, ...]) -> dict[str, dict[str, float | str]]:
    if len(labels) != len(scores) or not labels:
        raise ValueError("metric inputs must have equal non-zero length")
    if any(label not in {0, 1} for label in labels):
        raise ValueError("binary targets must be 0 or 1")
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("metric scores must be finite")
    positives = tuple(score for label, score in zip(labels, scores, strict=True) if label == 1)
    negatives = tuple(score for label, score in zip(labels, scores, strict=True) if label == 0)
    if not positives or not negatives:
        undefined = _undefined()
        return {"pr_auc": dict(undefined), "roc_auc": dict(undefined)}

    false_positive_rate, true_positive_rate, _roc_thresholds = roc_curve(labels, scores)
    precision, recall, _pr_thresholds = precision_recall_curve(labels, scores)
    roc_auc = float(auc(false_positive_rate, true_positive_rate))
    pr_auc = float(auc(recall, precision))
    if not math.isfinite(roc_auc) or not math.isfinite(pr_auc):
        raise ValueError("defined metrics must be finite")
    return {
        "pr_auc": {"status": "DEFINED", "value": pr_auc},
        "roc_auc": {"status": "DEFINED", "value": roc_auc},
    }


def postprocess_for_config(config_id: str) -> tuple[str, float | None]:
    if config_id in _GAUSSIAN_CONFIGS:
        return GAUSSIAN_POSTPROCESS, 10.0
    if config_id in _DIRECT_CONFIGS:
        return DIRECT_B4_POSTPROCESS, None
    raise ValueError("unregistered experiment configuration")


def temporal_protocol_for_config(config_id: str) -> str:
    if config_id in {"O0", "O1", "I0", "I1", "I2", "I3", "I4"}:
        return OFFLINE_PROTOCOL
    if config_id in {"C0", "C1"}:
        return CAUSAL_PROTOCOL
    if config_id == "S0":
        return STREAM_CAUSAL_PROTOCOL
    raise ValueError("unregistered experiment configuration")


def project_video_predictions(
    predictions: Sequence[Mapping[str, Any]],
    *,
    frame_count: int,
    frame_interval: int,
    gaussian_sigma: float | None,
) -> tuple[float, ...]:
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise ValueError("frame_count must be a positive integer")
    if isinstance(frame_interval, bool) or not isinstance(frame_interval, int) or frame_interval <= 0:
        raise ValueError("frame_interval must be a positive integer")
    expected_count = (frame_count + frame_interval - 1) // frame_interval
    ordered = tuple(sorted(predictions, key=lambda item: int(item["window_ordinal"])))
    if len(ordered) != expected_count:
        raise ValueError("prediction grid does not cover every original frame")

    scores: list[float] = []
    video_id: str | None = None
    for ordinal, record in enumerate(ordered):
        current_video_id = str(record["video_id"])
        video_id = current_video_id if video_id is None else video_id
        expected_start = ordinal * frame_interval
        expected_end = min(expected_start + frame_interval, frame_count) - 1
        if (
            current_video_id != video_id
            or int(record["window_ordinal"]) != ordinal
            or str(record["window_id"]) != window_semantic_id(video_id, ordinal)
            or int(record["start_frame"]) != expected_start
            or int(record["end_frame"]) != expected_end
            or int(record["frame_count"]) != frame_count
            or int(record["frame_interval"]) != frame_interval
        ):
            raise ValueError("prediction grid metadata is invalid")
        score = float(record["prediction"])
        if not math.isfinite(score):
            raise ValueError("prediction scores must be finite")
        scores.append(score)

    decision_scores = np.asarray(scores, dtype=np.float64)
    if gaussian_sigma is not None:
        if not math.isfinite(gaussian_sigma) or gaussian_sigma <= 0.0:
            raise ValueError("gaussian sigma must be positive and finite")
        decision_scores = gaussian_filter1d(decision_scores, sigma=gaussian_sigma)
    projected = np.repeat(decision_scores, frame_interval)[:frame_count]
    if projected.size != frame_count:
        raise ValueError("prediction grid projection is incomplete")
    return tuple(float(value) for value in projected)


def frame_labels(
    frame_count: int,
    anomaly_intervals: Sequence[tuple[int, int]],
    *,
    normal_label: int,
) -> tuple[int, ...]:
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise ValueError("frame_count must be a positive integer")
    if normal_label != 0:
        raise ValueError("formal MVP frame targets require normal_label=0")
    labels = [0] * frame_count
    previous_start = -1
    for start_frame, end_frame in anomaly_intervals:
        if (
            isinstance(start_frame, bool)
            or isinstance(end_frame, bool)
            or not isinstance(start_frame, int)
            or not isinstance(end_frame, int)
            or start_frame < 0
            or end_frame < start_frame
            or end_frame >= frame_count
            or start_frame < previous_start
        ):
            raise ValueError("anomaly intervals must be ordered inclusive frame ranges")
        labels[start_frame : end_frame + 1] = [1] * (end_frame - start_frame + 1)
        previous_start = start_frame
    return tuple(labels)


def evaluate_frame_predictions(
    predictions: Sequence[Mapping[str, Any]],
    target_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "dataset_id",
        "experiment_config_id",
        "frame_interval",
        "manifest_type",
        "normal_label",
        "postprocess_identity",
        "temporal_protocol",
        "videos",
    }
    if set(target_manifest) != required or target_manifest.get("manifest_type") != FRAME_TARGET_MANIFEST_TYPE:
        raise ValueError("Evaluator frame target manifest is invalid")
    frame_interval = target_manifest["frame_interval"]
    normal_label = target_manifest["normal_label"]
    if frame_interval != 16 or normal_label != 0:
        raise ValueError("formal evaluator requires frame_interval=16 and normal_label=0")
    postprocess_identity, gaussian_sigma = postprocess_for_config(str(target_manifest["experiment_config_id"]))
    if target_manifest["postprocess_identity"] != postprocess_identity:
        raise ValueError("target postprocess identity does not match experiment configuration")
    expected_temporal_protocol = temporal_protocol_for_config(str(target_manifest["experiment_config_id"]))
    if target_manifest["temporal_protocol"] != expected_temporal_protocol:
        raise ValueError("target temporal protocol does not match experiment configuration")

    videos = target_manifest["videos"]
    if not isinstance(videos, list) or not videos:
        raise ValueError("Evaluator frame target manifest requires videos")
    video_ids = [str(video["video_id"]) for video in videos]
    if len(video_ids) != len(set(video_ids)) or video_ids != sorted(video_ids, key=lambda value: value.encode("utf-8")):
        raise ValueError("target videos must be unique and canonically ordered")

    prediction_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in predictions:
        prediction_groups[str(record["video_id"])].append(record)
    if set(prediction_groups) != set(video_ids):
        raise ValueError("frame targets do not cover frozen prediction videos exactly")

    labels: list[int] = []
    scores: list[float] = []
    for video in videos:
        if not isinstance(video, dict) or set(video) != {"anomaly_intervals", "frame_count", "video_id"}:
            raise ValueError("Evaluator frame target video is invalid")
        video_id = str(video["video_id"])
        frame_count = int(video["frame_count"])
        raw_intervals = video["anomaly_intervals"]
        if not isinstance(raw_intervals, list):
            raise ValueError("anomaly intervals must be a list")
        intervals: list[tuple[int, int]] = []
        for interval in raw_intervals:
            if not isinstance(interval, dict) or set(interval) != {"end_frame", "start_frame"}:
                raise ValueError("anomaly interval fields are invalid")
            intervals.append((interval["start_frame"], interval["end_frame"]))
        labels.extend(frame_labels(frame_count, intervals, normal_label=normal_label))
        scores.extend(
            project_video_predictions(
                prediction_groups[video_id],
                frame_count=frame_count,
                frame_interval=frame_interval,
                gaussian_sigma=gaussian_sigma,
            )
        )
    return {
        "frame_count": len(labels),
        "metrics": evaluate_binary_metrics(tuple(labels), tuple(scores)),
        "postprocess_identity": postprocess_identity,
        "video_count": len(videos),
    }
