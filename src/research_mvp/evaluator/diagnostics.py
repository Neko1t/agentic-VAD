from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .metrics import FRAME_TARGET_MANIFEST_TYPE, frame_labels, postprocess_for_config, project_video_predictions


EVALUATOR_DIAGNOSTIC_SCHEMA_VERSION = "MVP_EVALUATOR_DIAGNOSTIC_V1"


def _key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item["video_id"]), str(item["window_id"])


def _frame_join(
    predictions: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[tuple[str, str], tuple[dict[str, Any], float]]:
    frame_interval = int(manifest["frame_interval"])
    _postprocess, gaussian_sigma = postprocess_for_config(str(manifest["experiment_config_id"]))
    prediction_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        prediction_groups[str(prediction["video_id"])].append(prediction)
    joined: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
    for video in manifest["videos"]:
        video_id = str(video["video_id"])
        frame_count = int(video["frame_count"])
        intervals = tuple(
            (int(interval["start_frame"]), int(interval["end_frame"]))
            for interval in video["anomaly_intervals"]
        )
        labels = frame_labels(frame_count, intervals, normal_label=int(manifest["normal_label"]))
        ordered = tuple(sorted(prediction_groups[video_id], key=lambda item: int(item["window_ordinal"])))
        postprocessed = project_video_predictions(
            ordered,
            frame_count=frame_count,
            frame_interval=frame_interval,
            gaussian_sigma=gaussian_sigma,
        )
        for prediction in ordered:
            start = int(prediction["start_frame"])
            end = int(prediction["end_frame"])
            positive_count = sum(labels[start : end + 1])
            window_count = end - start + 1
            joined[_key(prediction)] = (
                {
                    "kind": "FRAME_FRACTION",
                    "positive_fraction": positive_count / window_count,
                    "positive_frame_count": positive_count,
                    "window_frame_count": window_count,
                },
                float(postprocessed[start]),
            )
    return joined


def _window_join(
    predictions: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[tuple[str, str], tuple[dict[str, Any], float]]:
    values = {
        (str(record["video_id"]), str(record["window_id"])): int(record["target"])
        for record in manifest["records"]
    }
    return {
        _key(prediction): (
            {"kind": "WINDOW_BINARY", "value": values[_key(prediction)]},
            float(prediction["prediction"]),
        )
        for prediction in predictions
    }


def build_evaluator_diagnostic_report(
    predictions: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    target_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    ordered_predictions = tuple(
        sorted(predictions, key=lambda item: (str(item["video_id"]).encode("utf-8"), int(item["window_ordinal"])))
    )
    diagnostics_by_key = {_key(item): item for item in diagnostics}
    if len(diagnostics_by_key) != len(diagnostics) or set(diagnostics_by_key) != {_key(item) for item in ordered_predictions}:
        raise ValueError("Evaluator diagnostics do not cover frozen predictions exactly")
    if set(target_manifest) == {"records"}:
        joined = _window_join(ordered_predictions, target_manifest)
    elif target_manifest.get("manifest_type") == FRAME_TARGET_MANIFEST_TYPE:
        joined = _frame_join(ordered_predictions, target_manifest)
    else:
        raise ValueError("Evaluator target manifest is invalid")

    records: list[dict[str, Any]] = []
    for prediction in ordered_predictions:
        key = _key(prediction)
        diagnostic = diagnostics_by_key[key]
        stages = diagnostic["b2"]["stages"]
        base = next(stage for stage in stages if stage["slot"] == "B2:base")
        final = next(stage for stage in stages if stage["slot"] == "B2:final")
        steps = [stage for stage in stages if str(stage["slot"]).startswith("B2:step-")]
        target, postprocess_score = joined[key]
        records.append(
            {
                "stage_scores": {
                    "b2_final": {
                        "conflict": final["conflict"],
                        "evidence": final["e_local"],
                        "quality": final["quality"],
                        "uncertainty": final["u_local"],
                    },
                    "b2_steps": [
                        {
                            "conflict": step["conflict"],
                            "evidence": step["e_local"],
                            "quality": step["quality"],
                            "slot": step["slot"],
                            "uncertainty": step["u_local"],
                        }
                        for step in steps
                    ],
                    "b4": {
                        "score": diagnostic["prediction"]["score"],
                        "score_interval": diagnostic["b4"]["audit"]["score_interval"],
                        "state": diagnostic["b4"]["audit"]["new_state"],
                    },
                    "b6": {
                        "evidence": diagnostic["b6"]["audit"]["output_evidence"],
                        "mode": diagnostic["b6"]["audit"]["mode"],
                        "reliability": diagnostic["b6"]["audit"]["output_reliability"],
                        "uncertainty": diagnostic["b6"]["audit"]["output_uncertainty"],
                    },
                    "postprocess": {"score": postprocess_score},
                    "vlm_base": {
                        "conflict": base["conflict"],
                        "evidence": base["e_local"],
                        "quality": base["quality"],
                        "uncertainty": base["u_local"],
                    },
                },
                "target": target,
                "tool_actions": diagnostic["b3"]["tool_actions"],
                "video_id": key[0],
                "window_id": key[1],
                "window_ordinal": int(prediction["window_ordinal"]),
            }
        )
    return {
        "records": records,
        "schema_version": EVALUATOR_DIAGNOSTIC_SCHEMA_VERSION,
    }
