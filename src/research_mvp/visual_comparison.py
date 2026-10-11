"""Outer, read-only-input coordinator for a separately invoked post-freeze comparison."""

from __future__ import annotations

import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any, Mapping

from .adapters.real_assets import load_precomputed_input
from .adapters.semantic_scores import MAPPING_IDENTITY, load_semantic_score_manifest
from .artifacts.hashes import bytes_sha256, file_sha256
from .artifacts.publisher import MvpImmutablePublisher
from .artifacts.resolver import resolve_relative, validate_path_identity
from .codec import dumps, loads
from .evaluator.resolver import MvpEvaluatorResolver
from .evaluator.visual_comparison import build_visual_comparison
from .failures import fatal
from .launcher import verify_frozen_attempt
from .media import OFFLINE_PROTOCOL


def _metric(value: Mapping[str, Any]) -> str:
    return f"{value['value']:.6f}" if value["status"] == "DEFINED" else "未定义（单类别）"


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# 视觉单模态最低版：同输入对照",
        "",
        "> NO_RESEARCH_CLAIM：用于开题预实验，不构成正式统计结论。",
        "",
        f"视频数：{report['video_count']}；窗口数：{report['window_count']}；帧数：{report['frame_count']}；"
        f"异常帧数：{report['positive_frame_count']}。",
        "",
        "## 实验配置与池化帧级指标",
        "",
        "三组使用相同视觉描述、Llama 分数、标注和 16 帧网格。PR AUC 使用梯形积分，不是 AP。",
        "",
        "| 配置 | 分数处理 | OCR/Audio | Memory | ROC AUC | PR AUC |",
        "|---|---|---|---|---:|---:|",
    ]
    descriptions = {
        "V0": "原始 Llama 分数，无时序处理",
        "V1": "作者式 Gaussian σ=10（先平滑再帧展开）",
        "V2": "现有标量映射＋B2/B4，无额外 Gaussian",
    }
    for arm, result in report["arms"].items():
        lines.append(
            f"| {arm} | {descriptions[arm]} | 关闭 | 关闭 | "
            f"{_metric(result['metrics']['roc_auc'])} | {_metric(result['metrics']['pr_auc'])} |"
        )
    lines.extend(
        [
            "",
            "## 逐视频结果",
            "",
            "全正常视频的 AUC 保持未定义；均分/最高分供误报排查，不是阈值报警指标。",
            "",
            "| 视频 | 配置 | ROC AUC | PR AUC | 平均分 | 最高分 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for video_id in report["arms"]["V0"]["per_video"]:
        for arm, result in report["arms"].items():
            row = result["per_video"][video_id]
            lines.append(
                f"| {video_id} | {arm} | {_metric(row['metrics']['roc_auc'])} | "
                f"{_metric(row['metrics']['pr_auc'])} | {row['score_mean']:.6f} | {row['score_max']:.6f} |"
            )
    lines.extend(
        [
            "",
            "## 解释边界与可复现来源",
            "",
            report["interpretation_zh"],
            "",
            f"LLM 解析状态：{report['parse_status_counts']}。INTERPOLATED 如非零，表示既有离线插值而非真实模型输出。",
            "",
            "V2 每个窗口均已检查工具调用为空、B6 为 IDENTITY_DISABLED。",
            "",
            "窗口描述、预处理抽帧信息（若源清单提供）、三组分数及标注占比见 window_scores.jsonl。",
            "当前 VLM 从原视频内部采样，预处理帧号不代表 VLM 实际输入帧；其精确采样轨迹尚未记录。",
            "完整精度指标及输入/代码/环境哈希见 comparison.json；文件完整性见 receipt.json。",
            "",
            f"来源 attempt：`{report['provenance']['attempt_id']}`。",
            f"来源输入模式：`{report['provenance']['source_asset_profile']}`；ALL 表示复用历史多模态预计算包，"
            "并不表示本次推理使用了 OCR/Audio。",
            "",
        ]
    )
    return "\n".join(lines)


def compare_visual_attempt(
    *,
    project_root: Path,
    attempt_id: str,
    input_manifest_path: Path,
    semantic_score_manifest_path: Path,
    semantic_score_manifest_sha256: str,
    target_manifest_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Run only after inference has exited; never start inference or modify its artifacts."""
    validate_path_identity(output_root)
    comparison_root = (project_root / "data/agentic_outputs/mvp/comparisons").resolve()
    try:
        relative = output_root.resolve().relative_to(comparison_root)
    except ValueError as exc:
        raise fatal("MVP_PATH_ESCAPE", "comparison output must be under the dedicated comparisons directory") from exc
    if not relative.parts or output_root.exists():
        raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "comparison output must be a fresh child directory")

    verified = verify_frozen_attempt(project_root, attempt_id, inference_quiescent=True)
    fixture, bundle, _ = load_precomputed_input(input_manifest_path)
    load_semantic_score_manifest(
        semantic_score_manifest_path,
        expected_sha256=semantic_score_manifest_sha256,
        input_manifest_path=input_manifest_path,
    )
    plan = verified["plan"]
    if (
        plan.get("tool_policy") != "NONE"
        or plan.get("tool_action_order") != []
        or plan.get("fixture_sha256") != file_sha256(input_manifest_path)
        or plan.get("asset_bundle_manifest_sha256") != fixture["asset_bundle_manifest_sha256"]
        or plan.get("semantic_score_manifest_sha256") != semantic_score_manifest_sha256
        or plan.get("semantic_mapping_identity") != MAPPING_IDENTITY
        or plan.get("temporal_protocol") != OFFLINE_PROTOCOL
        or plan.get("frame_interval") != 16
    ):
        raise fatal("MVP_FREEZE_INVALID", "attempt does not bind the requested visual comparison inputs")

    entries = [
        entry
        for entry in verified["output_manifest"]["entries"]
        if entry["artifact_type"] in {"predictions", "diagnostic-window", "trace"}
    ]
    resolver = MvpEvaluatorResolver(
        verified["inference_root"], tuple((e["relative_ref"], e["byte_length"], e["sha256"]) for e in entries)
    )
    predictions: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for entry in entries:
        raw = resolver.read(entry["relative_ref"])
        if entry["artifact_type"] == "predictions":
            predictions.extend(loads(line) for line in raw.splitlines() if line)
        elif entry["artifact_type"] == "diagnostic-window":
            diagnostics.append(loads(raw))
        elif entry["relative_ref"] == "traces/tool_trace.jsonl" and raw.strip():
            raise fatal("MVP_FREEZE_INVALID", "visual comparison requires zero tool calls")

    # This command is an outer post-freeze consumer; targets are first read here, never in inference.
    validate_path_identity(target_manifest_path)
    target_hash = file_sha256(target_manifest_path)
    target = loads(target_manifest_path.read_bytes())
    if (
        target.get("dataset_id") != fixture["dataset_id"]
        or target.get("temporal_protocol") != fixture["temporal_protocol"]
    ):
        raise ValueError("comparison targets do not match the source dataset/protocol")
    semantic = loads(semantic_score_manifest_path.read_bytes())
    report, rows = build_visual_comparison(predictions, diagnostics, semantic["scores"], target)

    raw_records = {entry["artifact_id"]: entry for entry in bundle["raw_output_artifacts"]}
    windows = {(v["video_id"], w["window_id"]): w for v in fixture["videos"] for w in v["windows"]}
    for row in rows:
        record = raw_records[f"raw:{row['video_id']}/{row['window_id']}:caption"]
        caption_path = resolve_relative(input_manifest_path.parent, record["relative_ref"])
        if file_sha256(caption_path) != row["caption_payload_hash"]:
            raise fatal("MVP_FREEZE_INVALID", "comparison caption changed")
        row["caption"] = loads(caption_path.read_bytes())["text"]
        window = windows[(row["video_id"], row["window_id"])]
        row["evidence_start_us"] = window["evidence_start_us"]
        row["evidence_end_us"] = window["evidence_end_us"]
        row["sampled_frame_indices"] = window.get("sampled_frame_indices")
        row["sampled_frame_timestamps_us"] = window.get("sampled_frame_timestamps_us")
        row["frame_metadata_role"] = "MEDIA_PREPARATION_ONLY"
        row["caption_input_mode"] = "VIDEO_PATH_PROCESSOR_SAMPLING"

    report["provenance"] = {
        "attempt_id": attempt_id,
        "inference_freeze_sha256": verified["inference_freeze_hash"],
        "input_manifest_sha256": file_sha256(input_manifest_path),
        "asset_bundle_manifest_sha256": fixture["asset_bundle_manifest_sha256"],
        "semantic_score_manifest_sha256": semantic_score_manifest_sha256,
        "target_manifest_sha256": target_hash,
        "source_asset_profile": fixture.get("asset_profile", "ALL"),
        "semantic_mapping_identity": MAPPING_IDENTITY,
        "semantic_model": semantic["model_provenance"],
        "visual_model_config": bundle["model_config"],
        "visual_model_identity": bundle["model_identity_payload_hash"],
        "inference_source_files": plan["source_file_manifest"],
        "comparison_source_files": [
            {"file": path.name, "sha256": file_sha256(path)}
            for path in (
                Path(__file__),
                Path(__file__).parent / "evaluator/visual_comparison.py",
                Path(__file__).parent / "evaluator/metrics.py",
            )
        ],
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("numpy", "scipy", "scikit-learn")},
    }
    after = verify_frozen_attempt(project_root, attempt_id, inference_quiescent=True)
    if (
        after["hash_inventory"] != verified["hash_inventory"]
        or file_sha256(target_manifest_path) != target_hash
        or file_sha256(semantic_score_manifest_path) != semantic_score_manifest_sha256
        or file_sha256(input_manifest_path) != plan["fixture_sha256"]
    ):
        raise fatal("MVP_FREEZE_INVALID", "comparison source changed during evaluation")
    load_precomputed_input(input_manifest_path)
    files = {
        "comparison.json": dumps(report),
        "report_zh.md": _markdown(report).encode("utf-8"),
        "window_scores.jsonl": b"\n".join(dumps(row) for row in rows) + b"\n",
    }
    publisher = MvpImmutablePublisher(output_root, {name: name for name in (*files, "receipt.json")})
    artifact_receipts = []
    parents = (verified["inference_freeze_hash"], target_hash, semantic_score_manifest_sha256, plan["fixture_sha256"])
    for name, content in files.items():
        receipt = publisher.publish(name, content, bytes_sha256(content), parent_payload_hashes=parents)
        artifact_receipts.append(
            {"relative_ref": name, "sha256": receipt.file_hash, "byte_length": receipt.byte_length}
        )
    receipt_data = dumps(
        {
            "status_code": "VISUAL_COMPARISON_COMPLETED",
            "artifacts": artifact_receipts,
            "input_hashes": list(parents),
            "inference_memory_hashes_unchanged": True,
        }
    )
    final = publisher.publish(
        "receipt.json",
        receipt_data,
        bytes_sha256(receipt_data),
        parent_payload_hashes=tuple(row["sha256"] for row in artifact_receipts),
    )
    return {
        "status_code": "VISUAL_COMPARISON_COMPLETED",
        "output_root": str(output_root.resolve()),
        "receipt_sha256": final.file_hash,
        "video_count": report["video_count"],
        "window_count": len(rows),
    }
