from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.research_mvp.adapters.real_assets import (
    MvpPrecomputedEvidenceResolver,
    MvpRealModelConfig,
    inspect_real_assets,
    load_asset_source_manifest,
    precompute_asset_bundle,
    smoke_evidence_direction,
)
from src.research_mvp.cli import main as cli_main
from src.research_mvp.failures import MvpFailure
from src.research_mvp.launcher import run_asset_attempt, verify_frozen_attempt
from src.research_mvp.runtime.video_runner import run_precomputed_inference


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeRealBackends:
    identity = "FAKE_REAL_BACKENDS_V0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.embedding_inputs: list[str] = []

    def caption(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("CAPTION", str(window["window_id"])))
        text = "a quiet empty hallway" if "reference" in str(window["video_id"]) else "people fight near smoke"
        return {"backend_name": "fake-caption", "confidence": 0.9, "text": text}

    def ocr(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("OCR", str(window["window_id"])))
        texts = ["EXIT"] if "reference" in str(window["video_id"]) else ["FIRE ALARM"]
        return {"backend_name": "fake-ocr", "confidence": 0.8, "texts": texts}

    def audio(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("AUDIO", str(window["window_id"])))
        events = [] if "reference" in str(window["video_id"]) else ["distress_audio"]
        transcript = "calm room tone" if not events else "help scream alarm"
        return {
            "backend_name": "fake-audio",
            "confidence": 0.7,
            "events": events,
            "transcript": transcript,
        }

    def embedding(self, text: str, window: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("EMBEDDING", str(window["window_id"])))
        self.embedding_inputs.append(text)
        vector = [1.0, 0.0] if "reference" in str(window["video_id"]) else [0.0, 1.0]
        return {"backend_name": "fake-embedding", "fallback_used": False, "vector": vector}

    def close(self) -> None:
        return None


def _write_asset_inputs(tmp_path: Path) -> tuple[Path, Path, MvpRealModelConfig, Path]:
    asset_root = tmp_path / "assets"
    for video_id in ("mvp-video-real-reference", "mvp-video-real-salient"):
        (asset_root / "videos").mkdir(parents=True, exist_ok=True)
        (asset_root / "frames" / video_id).mkdir(parents=True, exist_ok=True)
        (asset_root / "audio").mkdir(parents=True, exist_ok=True)
        (asset_root / "videos" / f"{video_id}.mp4").write_bytes(b"video-" + video_id.encode())
        (asset_root / "audio" / f"{video_id}.wav").write_bytes(b"audio-" + video_id.encode())
        for ordinal in range(2):
            (asset_root / "frames" / video_id / f"{ordinal:04d}.jpg").write_bytes(
                b"frame-" + video_id.encode() + str(ordinal).encode()
            )

    videos = []
    for video_id in ("mvp-video-real-reference", "mvp-video-real-salient"):
        windows = []
        for ordinal in range(2):
            start_us = ordinal * 1_000_000
            windows.append(
                {
                    "audio_ref": f"audio/{video_id}.wav",
                    "delta_us": 1_000_000,
                    "end_frame": ordinal * 16 + 15,
                    "end_us": start_us + 1_000_000,
                    "frame_refs": [f"frames/{video_id}/{ordinal:04d}.jpg"],
                    "ordinal": ordinal,
                    "start_frame": ordinal * 16,
                    "start_us": start_us,
                    "window_id": f"{video_id}-window-{ordinal:04d}",
                }
            )
        videos.append(
            {
                "video_id": video_id,
                "video_ref": f"videos/{video_id}.mp4",
                "windows": windows,
            }
        )
    source_payload = {
        "dataset_id": "mvp-real-assets-test",
        "manifest_type": "MVP_REAL_ASSET_SOURCE_V0",
        "runtime_profile": "RESEARCH_MVP",
        "videos": videos,
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    model_root = tmp_path / "models"
    model_paths: dict[str, Path] = {}
    for name in ("caption", "ocr", "audio", "embedding"):
        path = model_root / name
        path.mkdir(parents=True)
        (path / "config.json").write_text(json.dumps({"model": name}), encoding="utf-8")
        (path / "weights.bin").write_bytes((name + "-weights").encode())
        model_paths[name] = path
    model_config = MvpRealModelConfig(
        caption_model=model_paths["caption"],
        ocr_model=model_paths["ocr"],
        audio_model=model_paths["audio"],
        embedding_model=model_paths["embedding"],
        gpu_device="0",
    )

    target_payload = {
        "records": [
            {
                "target": 0 if "reference" in video["video_id"] else 1,
                "video_id": video["video_id"],
                "window_id": window["window_id"],
            }
            for video in videos
            for window in video["windows"]
        ]
    }
    target_path = tmp_path / "targets.json"
    target_path.write_text(json.dumps(target_payload), encoding="utf-8")
    return asset_root, source_path, model_config, target_path


def _bundle(tmp_path: Path) -> tuple[Any, FakeRealBackends, Path]:
    asset_root, source_path, model_config, target_path = _write_asset_inputs(tmp_path)
    backends = FakeRealBackends()
    receipt = precompute_asset_bundle(
        bundle_id="mvp-real-bundle-a",
        source_manifest_path=source_path,
        asset_root=asset_root,
        bundle_root=tmp_path / "data" / "agentic_outputs" / "mvp" / "precomputed" / "mvp-real-bundle-a",
        model_config=model_config,
        backends=backends,
    )
    return receipt, backends, target_path


def test_real_source_manifest_is_label_free_ordered_and_root_bound(tmp_path: Path) -> None:
    asset_root, source_path, _models, _targets = _write_asset_inputs(tmp_path)
    loaded = load_asset_source_manifest(source_path, asset_root)

    assert [video["video_id"] for video in loaded["videos"]] == [
        "mvp-video-real-reference",
        "mvp-video-real-salient",
    ]
    assert [window["ordinal"] for window in loaded["videos"][0]["windows"]] == [0, 1]

    poisoned = json.loads(source_path.read_text(encoding="utf-8"))
    poisoned["labels"] = [0, 1]
    poisoned_path = tmp_path / "poisoned.json"
    poisoned_path.write_text(json.dumps(poisoned), encoding="utf-8")
    with pytest.raises(MvpFailure, match="MVP_GROUND_TRUTH_POISON"):
        load_asset_source_manifest(poisoned_path, asset_root)

    escaped = json.loads(source_path.read_text(encoding="utf-8"))
    escaped["videos"][0]["video_ref"] = "../outside.mp4"
    escaped_path = tmp_path / "escaped.json"
    escaped_path.write_text(json.dumps(escaped), encoding="utf-8")
    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        load_asset_source_manifest(escaped_path, asset_root)


def test_smoke_evidence_mapper_is_deterministic_bounded_and_conflict_abstains() -> None:
    assert smoke_evidence_direction("people fight near a fire alarm") == (1.0, ("alarm", "fight", "fire"))
    assert smoke_evidence_direction("a calm quiet empty hallway") == (-1.0, ("calm", "empty", "quiet"))
    assert smoke_evidence_direction("a quiet hallway where people fight") == (0.0, ("fight", "quiet"))
    assert smoke_evidence_direction("ordinary scene with a person") == (0.0, ())
    assert smoke_evidence_direction("people fight near a fire alarm") == smoke_evidence_direction(
        "people fight near a fire alarm"
    )


def test_model_assets_are_required_and_missing_assets_do_not_create_bundle(tmp_path: Path) -> None:
    asset_root, source_path, models, _targets = _write_asset_inputs(tmp_path)
    missing = MvpRealModelConfig(
        caption_model=models.caption_model,
        ocr_model=models.ocr_model,
        audio_model=tmp_path / "missing-audio-model",
        embedding_model=models.embedding_model,
        gpu_device="0",
    )
    status = inspect_real_assets(source_path, asset_root, missing)
    assert status["status_code"] == "ASSET_NOT_RUN"
    assert status["missing_assets"] == ["audio_model"]

    bundle_root = tmp_path / "bundle-must-not-exist"
    with pytest.raises(MvpFailure, match="ASSET_NOT_RUN"):
        precompute_asset_bundle(
            bundle_id="mvp-real-missing-a",
            source_manifest_path=source_path,
            asset_root=asset_root,
            bundle_root=bundle_root,
            model_config=missing,
            backends=FakeRealBackends(),
        )
    assert not bundle_root.exists()


def test_precompute_bundle_freezes_models_sources_raw_outputs_and_no_fallback(tmp_path: Path) -> None:
    receipt, backends, _target_path = _bundle(tmp_path)
    prepared = json.loads(receipt.input_manifest_path.read_bytes())
    bundle_manifest = json.loads(receipt.bundle_manifest_path.read_bytes())

    assert receipt.status_code == "ASSET_BUNDLE_FROZEN"
    assert prepared["manifest_type"] == "MVP_PRECOMPUTED_INPUT_V0"
    assert prepared["adapter_identity"] == "PRECOMPUTED_REAL_ASSET_EVIDENCE_MVP_V0"
    assert len(backends.calls) == 2 * 2 * 4
    assert all("FIRE ALARM" not in text and "help scream alarm" not in text for text in backends.embedding_inputs)
    assert len(bundle_manifest["model_files"]) == 8
    assert len(bundle_manifest["source_assets"]) == 2 * (1 + 1 + 2)
    assert len(bundle_manifest["raw_output_artifacts"]) == 2 * 2 * 4
    assert len(bundle_manifest["evidence_artifacts"]) == 2 * 2 * 3
    assert all(len(item["sha256"]) == 64 for item in bundle_manifest["raw_output_artifacts"])
    assert all(len(item["payload_hash"]) == 64 for item in bundle_manifest["evidence_artifacts"])
    assert b"label" not in receipt.input_manifest_path.read_bytes().lower()

    class FallbackEmbeddingBackends(FakeRealBackends):
        def embedding(self, text: str, window: Mapping[str, Any]) -> Mapping[str, Any]:
            result = dict(super().embedding(text, window))
            result["fallback_used"] = True
            return result

    asset_root, source_path, models, _targets = _write_asset_inputs(tmp_path / "fallback")
    with pytest.raises(MvpFailure, match="ASSET_NOT_RUN"):
        precompute_asset_bundle(
            bundle_id="mvp-real-fallback-a",
            source_manifest_path=source_path,
            asset_root=asset_root,
            bundle_root=tmp_path / "fallback-bundle",
            model_config=models,
            backends=FallbackEmbeddingBackends(),
        )


def test_precomputed_evidence_resolver_decodes_only_the_requested_action(tmp_path: Path) -> None:
    receipt, _backends, _target_path = _bundle(tmp_path)
    prepared = json.loads(receipt.input_manifest_path.read_bytes())
    window = prepared["videos"][0]["windows"][0]
    resolver = MvpPrecomputedEvidenceResolver(receipt.input_manifest_path.parent)

    assert resolver.decoded_actions == ()
    vlm = resolver.load("mvp-video-real-reference", window, "VLM")
    assert vlm["channel"] == "VLM"
    assert resolver.decoded_actions == (("mvp-video-real-reference-window-0000", "VLM"),)
    assert "OCR" not in {action for _window_id, action in resolver.decoded_actions}


def test_precomputed_inference_verifies_bundle_before_root_and_preserves_window_order(tmp_path: Path) -> None:
    receipt, _backends, _target_path = _bundle(tmp_path)
    summary = run_precomputed_inference(
        attempt_id="mvp-real-infer-a",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        memory_enabled=True,
    )

    assert summary["video_order"] == ["mvp-video-real-reference", "mvp-video-real-salient"]
    assert len(summary["window_traces"]) == 4
    assert all(trace["final_b2_count"] == 1 for trace in summary["window_traces"])
    assert all(trace["final_b6_count"] == 1 for trace in summary["window_traces"])
    assert all(trace["b4_commit_count"] == 1 for trace in summary["window_traces"])
    assert all(trace["payload_read_after_manifest_acceptance"] for trace in summary["window_traces"])
    plan = json.loads((Path(summary["output_attempt_root"]) / "inference" / "mvp_inference_plan.json").read_bytes())
    assert plan["adapter_identity"] == "PRECOMPUTED_REAL_ASSET_EVIDENCE_MVP_V0"
    assert plan["asset_bundle_manifest_sha256"] == receipt.bundle_manifest_sha256
    assert plan["precompute_provenance"]["backend_identity"] == "FAKE_REAL_BACKENDS_V0"
    assert plan["precompute_provenance"]["smoke_mapper_identity"] == "MVP_SMOKE_TEXT_EVIDENCE_V0"
    assert len(plan["precompute_provenance"]["model_files"]) == 8
    assert len(plan["precompute_provenance"]["source_assets"]) == 8
    assert plan["precompute_provenance"]["model_config"]["gpu_device"] == "0"
    assert plan["video_order"] == summary["video_order"]
    assert len(plan["raw_output_artifacts"]) == 16 + 12

    second_root = tmp_path / "tamper-run"
    receipt2, _backends2, _targets2 = _bundle(second_root)
    prepared2 = json.loads(receipt2.input_manifest_path.read_bytes())
    evidence_ref = prepared2["videos"][0]["windows"][0]["evidence_artifacts"]["VLM"]["relative_ref"]
    (receipt2.input_manifest_path.parent / evidence_ref).write_bytes(b"tampered")
    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        run_precomputed_inference(
            attempt_id="mvp-real-tampered-a",
            project_root=second_root,
            input_manifest_path=receipt2.input_manifest_path,
            memory_enabled=True,
        )
    assert not (second_root / "data" / "agentic_outputs" / "mvp" / "mvp-real-tampered-a").exists()
    assert not (second_root / "data" / "agentic_memory" / "mvp" / "mvp-real-tampered-a").exists()


def test_asset_outer_launcher_keeps_targets_out_of_inference_and_accepts_arbitrary_video_count(tmp_path: Path) -> None:
    receipt, _backends, target_path = _bundle(tmp_path)
    result = run_asset_attempt(
        attempt_id="mvp-real-outer-a",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        target_manifest_path=target_path,
        memory_enabled=True,
    )

    assert result["status_code"] == "EVALUATION_COMPLETED"
    assert result["inference_process_id"] != result["evaluator_process_id"]
    assert result["evaluator_started_after_inference_exit"] is True
    assert result["inference_memory_hashes_unchanged"] is True
    verified = verify_frozen_attempt(tmp_path, "mvp-real-outer-a", inference_quiescent=True)
    assert len(
        [entry for entry in verified["output_manifest"]["entries"] if entry["artifact_type"] == "prediction-freeze"]
    ) == 2
    inference_bytes = b"\n".join(
        path.read_bytes().lower()
        for path in (tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-real-outer-a" / "inference").rglob("*")
        if path.is_file()
    )
    assert b"label" not in inference_bytes
    assert b"annotation" not in inference_bytes
    assert target_path.name.encode() not in inference_bytes


def test_real_asset_cli_readiness_and_backend_import_boundary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    asset_root, source_path, models, _targets = _write_asset_inputs(tmp_path)
    missing_audio = tmp_path / "not-installed"
    exit_code = cli_main(
        [
            "inspect-real-assets",
            "--source-manifest",
            str(source_path),
            "--asset-root",
            str(asset_root),
            "--caption-model",
            str(models.caption_model),
            "--ocr-model",
            str(models.ocr_model),
            "--audio-model",
            str(missing_audio),
            "--embedding-model",
            str(models.embedding_model),
            "--gpu-device",
            "0",
        ]
    )
    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["status_code"] == "ASSET_NOT_RUN"

    source_root = REPO_ROOT / "src" / "research_mvp"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        for name in imported:
            if path.parent.name == "adapters":
                assert not name.startswith(("src.agents", "src.pipelines", "src.eval"))
                if name.startswith(("src.tools", "src.memory")):
                    assert name in {"src.tools.vlm_tool", "src.memory.embedding_builder"}
            else:
                assert not name.startswith(("src.tools", "src.memory.embedding_builder"))
