"""Pure, post-freeze visual baseline comparison; never an inference component."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .. import RESEARCH_CLAIM_STATUS
from ..media import OFFLINE_PROTOCOL
from .metrics import evaluate_binary_metrics, evaluate_frame_predictions, frame_labels, project_video_predictions


def _key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record["video_id"]), str(record["window_id"])


def build_visual_comparison(
    predictions: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    semantic_records: Sequence[Mapping[str, Any]],
    target_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare raw, author-style smoothing and a tools/memory-off B2/B4 attempt."""
    if (
        target_manifest.get("temporal_protocol") != OFFLINE_PROTOCOL
        or target_manifest.get("experiment_config_id") != "I3"
    ):
        raise ValueError("visual comparison requires the offline I3 frame evaluation protocol")
    # Reuse the formal evaluator's validation, inclusive labels, grid and PR definition.
    formal_v2 = evaluate_frame_predictions(predictions, target_manifest)
    predicted = {_key(row): row for row in predictions}
    semantic = {_key(row): row for row in semantic_records}
    audits = {_key(row): row for row in diagnostics}
    if (
        len(predicted) != len(predictions)
        or len(semantic) != len(semantic_records)
        or len(audits) != len(diagnostics)
        or set(predicted) != set(semantic)
        or set(predicted) != set(audits)
    ):
        raise ValueError("comparison must cover exactly the same unique windows")
    for key, prediction in predicted.items():
        diagnostic = audits[key]
        if (
            diagnostic["b6"]["audit"]["mode"] != "IDENTITY_DISABLED"
            or diagnostic["b3"]["attempted_actions"]
            or diagnostic["b3"]["tool_actions"]
            or diagnostic["prediction"]["score"] != prediction["prediction"]
            or semantic[key]["window_ordinal"] != prediction["window_ordinal"]
        ):
            raise ValueError("comparison requires matching predictions with tools and Memory disabled")

    configs = {
        "V0": {"name_zh": "原始视觉语义评分", "postprocess": "RAW_LLAMA_SCORE", "gaussian_sigma": None},
        "V1": {"name_zh": "作者式平滑基线", "postprocess": "AUTHOR_STYLE_GAUSSIAN", "gaussian_sigma": 10.0},
        "V2": {"name_zh": "当前时序机制原型", "postprocess": "CENTERED_MAPPING_B2_B4", "gaussian_sigma": None},
    }
    arms = {
        arm: {
            "config": {
                **config,
                "tool_policy": "NONE",
                "memory_enabled": False,
                "semantic_input": "SAME_FROZEN_LLAMA_SCORES",
            },
            "per_video": {},
        }
        for arm, config in configs.items()
    }
    pooled_scores: dict[str, list[float]] = {arm: [] for arm in arms}
    pooled_labels: list[int] = []
    rows: list[dict[str, Any]] = []
    for video in target_manifest["videos"]:
        video_id = str(video["video_id"])
        count = int(video["frame_count"])
        ordered = sorted(
            (row for row in predictions if row["video_id"] == video_id), key=lambda row: int(row["window_ordinal"])
        )
        raw_predictions = [{**row, "prediction": semantic[_key(row)]["anomaly_score"]} for row in ordered]
        labels = frame_labels(
            count, [(i["start_frame"], i["end_frame"]) for i in video["anomaly_intervals"]], normal_label=0
        )
        pooled_labels.extend(labels)
        projected: dict[str, tuple[float, ...]] = {}
        for arm, config in configs.items():
            scores = project_video_predictions(
                ordered if arm == "V2" else raw_predictions,
                frame_count=count,
                frame_interval=16,
                gaussian_sigma=config["gaussian_sigma"],
            )
            projected[arm] = scores
            pooled_scores[arm].extend(scores)
            arms[arm]["per_video"][video_id] = {
                "frame_count": count,
                "positive_frame_count": sum(labels),
                "metrics": evaluate_binary_metrics(labels, scores),
                # Undefined AUC for normal-only videos is intentional; these summaries still expose high scores.
                "score_mean": sum(scores) / count,
                "score_max": max(scores),
            }
        for prediction in ordered:
            key = _key(prediction)
            start, end = int(prediction["start_frame"]), int(prediction["end_frame"])
            final_b2 = next(stage for stage in audits[key]["b2"]["stages"] if stage["slot"] == "B2:final")
            rows.append(
                {
                    "video_id": video_id,
                    "window_id": key[1],
                    "window_ordinal": prediction["window_ordinal"],
                    "start_frame": start,
                    "end_frame": end,
                    **{arm: scores[start] for arm, scores in projected.items()},
                    "b2_evidence": final_b2["e_local"],
                    "b2_quality": final_b2["quality"],
                    "b4_state": audits[key]["b4"]["audit"]["new_state"],
                    "positive_frame_count": sum(labels[start : end + 1]),
                    "window_frame_count": end - start + 1,
                    "positive_fraction": sum(labels[start : end + 1]) / (end - start + 1),
                    "caption_payload_hash": semantic[key]["caption_payload_hash"],
                    "parse_status": semantic[key]["parse_status"],
                    "llm_raw_response": semantic[key]["raw_response"],
                }
            )
    for arm in arms:
        arms[arm]["metrics"] = evaluate_binary_metrics(tuple(pooled_labels), tuple(pooled_scores[arm]))
    if arms["V2"]["metrics"] != formal_v2["metrics"]:
        raise ValueError("V2 comparison must match the formal frame evaluator exactly")
    return {
        "schema_version": "MVP_VISUAL_COMPARISON_V1",
        "research_claim_status": RESEARCH_CLAIM_STATUS,
        "dataset_id": target_manifest["dataset_id"],
        "temporal_protocol": OFFLINE_PROTOCOL,
        "frame_interval": 16,
        "video_count": len(target_manifest["videos"]),
        "frame_count": len(pooled_labels),
        "positive_frame_count": sum(pooled_labels),
        "window_count": len(predictions),
        "parse_status_counts": dict(sorted(Counter(row["parse_status"] for row in semantic_records).items())),
        "arms": arms,
        "interpretation_zh": "V0/V1 为同一冻结分数的评估侧对照，不是独立模型推理。V1 不是完整复现原作者；"
        "V2 是简化证据映射和 B2/B4 的机制原型，不代表完整冻结设计；小样本不支持统计显著性声明。",
    }, rows
