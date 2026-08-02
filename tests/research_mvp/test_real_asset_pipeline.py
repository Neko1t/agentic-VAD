from __future__ import annotations

import ast
import json
import sys
from types import ModuleType
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.research_mvp.adapters.real_assets import (
    MvpPrecomputedEvidenceResolver,
    MvpRealModelConfig,
    inspect_real_assets,
    load_asset_source_manifest,
    load_precomputed_input,
    precompute_asset_bundle,
    smoke_evidence_direction,
)
from src.research_mvp.adapters.semantic_scores import (
    MAPPING_IDENTITY,
    ORIGINAL_CONTEXT_PROMPT,
    ORIGINAL_FORMAT_PROMPT,
    TransformersSemanticScoringBackend,
    load_semantic_score_manifest,
    precompute_semantic_scores,
    semantic_score_to_evidence,
)
from src.research_mvp.cli import main as cli_main
from src.research_mvp.artifacts.hashes import file_sha256
from src.research_mvp.codec import dumps
from src.research_mvp.failures import MvpFailure
from src.research_mvp.evaluator.metrics import DIRECT_B4_POSTPROCESS
from src.research_mvp.launcher import run_asset_attempt, verify_frozen_attempt
from src.research_mvp.media import OFFLINE_PROTOCOL, plan_video_windows
from src.research_mvp.runtime.video_runner import run_precomputed_inference


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeRealBackends:
    identity = "FAKE_REAL_BACKENDS_V0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.embedding_inputs: list[str] = []
        self.backend_windows: list[dict[str, Any]] = []

    def caption(self, window: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("CAPTION", str(window["window_id"])))
        self.backend_windows.append(dict(window))
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


class FakeSemanticScoringBackend:
    identity = "FAKE_TRANSFORMERS_LLM_SCORER_V1"
    provenance = {
        "model_id": "fake-llama-3.1-8b-instruct",
        "model_files": [],
        "torch_version": "test",
        "transformers_version": "test",
    }

    def score(self, captions: tuple[str, ...]) -> tuple[str, ...]:
        return tuple("[0.1]" if "quiet" in caption else "[0.9]" for caption in captions)

    def close(self) -> None:
        return None


def test_transformers_semantic_backend_uses_eager_attention_for_left_padded_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_torch = ModuleType("torch")
    fake_torch.__version__ = "test"
    fake_torch.bfloat16 = object()  # type: ignore[attr-defined]

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def empty_cache() -> None:
            return None

    fake_torch.cuda = FakeCuda()  # type: ignore[attr-defined]
    fake_transformers = ModuleType("transformers")
    fake_transformers.__version__ = "test"

    class FakeTokenizer:
        pad_token_id = 0
        padding_side = "right"

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*_args: Any, **_kwargs: Any) -> FakeTokenizer:
            return FakeTokenizer()

    class FakeModel:
        def eval(self) -> None:
            return None

    class FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(*_args: Any, **kwargs: Any) -> FakeModel:
            captured.update(kwargs)
            return FakeModel()

    fake_transformers.AutoTokenizer = FakeAutoTokenizer  # type: ignore[attr-defined]
    fake_transformers.AutoModelForCausalLM = FakeAutoModelForCausalLM  # type: ignore[attr-defined]
    fake_transformers.set_seed = lambda _seed: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")

    backend = TransformersSemanticScoringBackend(model_path, "0")
    try:
        assert captured["attn_implementation"] == "eager"
        assert backend.provenance["attention_implementation"] == "eager"
    finally:
        backend.close()


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


def _upgrade_source_to_v1(source_path: Path) -> None:
    source = json.loads(source_path.read_bytes())
    source.update(
        {
            "decision_stride_frames": 16,
            "evidence_context_frames": 160,
            "frame_rate": {"denominator": 1, "numerator": 16},
            "manifest_type": "MVP_REAL_ASSET_SOURCE_V1",
            "temporal_protocol": OFFLINE_PROTOCOL,
        }
    )
    for video in source["videos"]:
        video["frame_count"] = 32
        for window in video["windows"]:
            window.update(
                {
                    "evidence_end_frame": 31,
                    "evidence_end_us": 2_000_000,
                    "evidence_start_frame": 0,
                    "evidence_start_us": 0,
                }
            )
    source_path.write_text(json.dumps(source), encoding="utf-8")


def _v1_bundle(tmp_path: Path) -> tuple[Any, FakeRealBackends, Path]:
    asset_root, source_path, model_config, target_path = _write_asset_inputs(tmp_path)
    _upgrade_source_to_v1(source_path)
    backends = FakeRealBackends()
    receipt = precompute_asset_bundle(
        bundle_id="mvp-real-bundle-v1",
        source_manifest_path=source_path,
        asset_root=asset_root,
        bundle_root=tmp_path / "data" / "agentic_outputs" / "mvp" / "precomputed" / "mvp-real-bundle-v1",
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


def test_v1_source_manifest_accepts_more_decisions_than_memory_capacity(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    (asset_root / "videos").mkdir(parents=True)
    (asset_root / "frames").mkdir()
    (asset_root / "audio").mkdir()
    (asset_root / "videos" / "long.mp4").write_bytes(b"video")
    (asset_root / "frames" / "shared.jpg").write_bytes(b"frame")
    (asset_root / "audio" / "shared.wav").write_bytes(b"audio")
    planned = plan_video_windows(
        video_id="mvp-video-long",
        frame_count=8208,
        fps_num=30,
        fps_den=1,
        temporal_protocol=OFFLINE_PROTOCOL,
    )
    assert len(planned) == 513
    windows = [
        {
            "audio_ref": "audio/shared.wav",
            "delta_us": window.delta_us,
            "end_frame": window.end_frame,
            "end_us": window.end_us,
            "evidence_end_frame": window.evidence_end_frame,
            "evidence_end_us": window.evidence_end_us,
            "evidence_start_frame": window.evidence_start_frame,
            "evidence_start_us": window.evidence_start_us,
            "frame_refs": ["frames/shared.jpg"],
            "ordinal": window.ordinal,
            "start_frame": window.start_frame,
            "start_us": window.start_us,
            "window_id": window.window_id,
        }
        for window in planned
    ]
    source = {
        "dataset_id": "long-grid",
        "decision_stride_frames": 16,
        "evidence_context_frames": 300,
        "frame_rate": {"denominator": 1, "numerator": 30},
        "manifest_type": "MVP_REAL_ASSET_SOURCE_V1",
        "runtime_profile": "RESEARCH_MVP",
        "temporal_protocol": OFFLINE_PROTOCOL,
        "videos": [
            {
                "frame_count": 8208,
                "video_id": "mvp-video-long",
                "video_ref": "videos/long.mp4",
                "windows": windows,
            }
        ],
    }
    source_path = tmp_path / "source-v1.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    loaded = load_asset_source_manifest(source_path, asset_root)

    assert len(loaded["videos"][0]["windows"]) == 513


def test_v1_precompute_uses_evidence_context_and_freezes_decision_metadata(tmp_path: Path) -> None:
    receipt, backends, _target_path = _v1_bundle(tmp_path)
    prepared = json.loads(receipt.input_manifest_path.read_bytes())

    assert prepared["manifest_type"] == "MVP_PRECOMPUTED_INPUT_V1"
    assert prepared["adapter_identity"] == "PRECOMPUTED_REAL_ASSET_EVIDENCE_MVP_V1"
    assert prepared["decision_point_count"] == 4
    first_backend_window = backends.backend_windows[0]
    assert (first_backend_window["start_frame"], first_backend_window["end_frame"]) == (0, 31)
    assert (first_backend_window["decision_start_frame"], first_backend_window["decision_end_frame"]) == (0, 15)

    materialized, _bundle_manifest, _resolver = load_precomputed_input(receipt.input_manifest_path)
    first = materialized["videos"][0]["windows"][0]
    assert first["frame_count"] == 32
    assert (first["start_frame"], first["end_frame"]) == (0, 15)
    assert (first["evidence_start_frame"], first["evidence_end_frame"]) == (0, 31)

    summary = run_precomputed_inference(
        attempt_id="mvp-real-v1-infer-a",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        memory_enabled=True,
    )
    prediction_path = (
        Path(summary["output_attempt_root"])
        / "inference"
        / "predictions"
        / "mvp-video-real-reference.jsonl"
    )
    prediction = json.loads(prediction_path.read_bytes().splitlines()[0])
    assert prediction["frame_count"] == 32
    assert prediction["frame_interval"] == 16
    assert (prediction["start_frame"], prediction["end_frame"]) == (0, 15)


def test_v1_outer_launcher_evaluates_frozen_predictions_at_frame_level(tmp_path: Path) -> None:
    receipt, _backends, _old_targets = _v1_bundle(tmp_path)
    target_path = tmp_path / "frame-targets-v1.json"
    target_path.write_text(
        json.dumps(
            {
                "dataset_id": "mvp-real-assets-test",
                "experiment_config_id": "I3",
                "frame_interval": 16,
                "manifest_type": "MVP_FRAME_TARGETS_V1",
                "normal_label": 0,
                "postprocess_identity": DIRECT_B4_POSTPROCESS,
                "temporal_protocol": OFFLINE_PROTOCOL,
                "videos": [
                    {
                        "anomaly_intervals": [],
                        "frame_count": 32,
                        "video_id": "mvp-video-real-reference",
                    },
                    {
                        "anomaly_intervals": [{"end_frame": 31, "start_frame": 0}],
                        "frame_count": 32,
                        "video_id": "mvp-video-real-salient",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_asset_attempt(
        attempt_id="mvp-real-v1-outer-a",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        target_manifest_path=target_path,
        memory_enabled=True,
    )

    assert result["status_code"] == "EVALUATION_COMPLETED"
    metrics_path = tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-real-v1-outer-a" / result["metrics_ref"]
    metrics = json.loads(metrics_path.read_bytes())
    assert metrics["evaluation_level"] == "FRAME"
    assert metrics["frame_count"] == 64
    assert metrics["postprocess_identity"] == DIRECT_B4_POSTPROCESS
    assert metrics["metrics"]["roc_auc"]["status"] == "DEFINED"


def test_smoke_evidence_mapper_is_deterministic_bounded_and_conflict_abstains() -> None:
    assert smoke_evidence_direction("people fight near a fire alarm") == (1.0, ("alarm", "fight", "fire"))
    assert smoke_evidence_direction("a calm quiet empty hallway") == (-1.0, ("calm", "empty", "quiet"))
    assert smoke_evidence_direction("a quiet hallway where people fight") == (0.0, ("fight", "quiet"))
    assert smoke_evidence_direction("ordinary scene with a person") == (0.0, ())
    assert smoke_evidence_direction("people fight near a fire alarm") == smoke_evidence_direction(
        "people fight near a fire alarm"
    )


@pytest.mark.parametrize(
    ("score", "expected_direction", "expected_quality", "expected_atom_count"),
    [
        (0.0, -1.0, 1.0, 1),
        (0.1, -1.0, 0.8, 1),
        (0.5, 0.0, 0.0, 0),
        (0.9, 1.0, 0.8, 1),
        (1.0, 1.0, 1.0, 1),
    ],
)
def test_semantic_score_mapping_is_centered_continuous_b2_evidence(
    tmp_path: Path,
    score: float,
    expected_direction: float,
    expected_quality: float,
    expected_atom_count: int,
) -> None:
    receipt, _backends, _targets = _bundle(tmp_path)
    prepared, _bundle_manifest, resolver = load_precomputed_input(receipt.input_manifest_path)
    window = prepared["videos"][0]["windows"][0]
    base = resolver.load(prepared["videos"][0]["video_id"], window, "VLM")

    mapped = semantic_score_to_evidence(base, score)

    assert mapped["direction"] == pytest.approx(expected_direction)
    assert mapped["q_in"] == pytest.approx(expected_quality)
    assert len(mapped["atoms"]) == expected_atom_count
    assert mapped["semantic_mapping_identity"] == MAPPING_IDENTITY
    if mapped["atoms"]:
        assert mapped["atoms"][0]["q_in"] == pytest.approx(expected_quality)
        assert mapped["atoms"][0]["direction"] == pytest.approx(expected_direction)


def test_semantic_score_manifest_is_complete_deterministic_hash_bound_and_label_free(tmp_path: Path) -> None:
    receipt, _backends, _targets = _bundle(tmp_path)
    first = precompute_semantic_scores(
        input_manifest_path=receipt.input_manifest_path,
        output_root=tmp_path / "semantic-a",
        backend=FakeSemanticScoringBackend(),
    )
    second = precompute_semantic_scores(
        input_manifest_path=receipt.input_manifest_path,
        output_root=tmp_path / "semantic-b",
        backend=FakeSemanticScoringBackend(),
    )

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    manifest = json.loads(first.manifest_path.read_bytes())
    assert manifest["context_prompt"] == ORIGINAL_CONTEXT_PROMPT
    assert manifest["format_prompt"] == ORIGINAL_FORMAT_PROMPT
    assert manifest["mapping_identity"] == MAPPING_IDENTITY
    assert manifest["score_count"] == 4
    assert len(manifest["scores"]) == 4
    assert b"label" not in first.manifest_path.read_bytes().lower()
    resolver = load_semantic_score_manifest(
        first.manifest_path,
        expected_sha256=first.manifest_sha256,
        input_manifest_path=receipt.input_manifest_path,
    )
    prepared, _bundle_manifest, evidence = load_precomputed_input(receipt.input_manifest_path)
    video = prepared["videos"][0]
    window = video["windows"][0]
    base = evidence.load(video["video_id"], window, "VLM")
    assert resolver.map_evidence(video["video_id"], window, base)["q_in"] == pytest.approx(0.8)

    tampered = dict(manifest)
    tampered["scores"] = [dict(item) for item in manifest["scores"]]
    tampered["scores"][0]["anomaly_score"] = 0.2
    first.manifest_path.write_bytes(dumps(tampered))
    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        load_semantic_score_manifest(
            first.manifest_path,
            expected_sha256=first.manifest_sha256,
            input_manifest_path=receipt.input_manifest_path,
        )

    incomplete_path = tmp_path / "incomplete-semantic.json"
    incomplete = dict(manifest)
    incomplete["scores"] = list(manifest["scores"][:-1])
    incomplete["score_count"] = len(incomplete["scores"])
    incomplete_path.write_bytes(dumps(incomplete))
    with pytest.raises(MvpFailure, match="MVP_FREEZE_INVALID"):
        load_semantic_score_manifest(
            incomplete_path,
            expected_sha256=file_sha256(incomplete_path),
            input_manifest_path=receipt.input_manifest_path,
        )

    poisoned_path = tmp_path / "poisoned-semantic.json"
    poisoned = dict(manifest)
    poisoned["label"] = 1
    poisoned_path.write_bytes(dumps(poisoned))
    with pytest.raises(MvpFailure, match="MVP_GROUND_TRUTH_POISON"):
        load_semantic_score_manifest(
            poisoned_path,
            expected_sha256=file_sha256(poisoned_path),
            input_manifest_path=receipt.input_manifest_path,
        )


def test_tool_policy_none_is_zero_action_and_default_all_is_prediction_compatible(tmp_path: Path) -> None:
    receipt, _backends, _targets = _bundle(tmp_path)

    default_run = run_precomputed_inference(
        attempt_id="mvp-tool-default-all",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        memory_enabled=False,
    )
    explicit_all = run_precomputed_inference(
        attempt_id="mvp-tool-explicit-all",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        memory_enabled=False,
        tool_policy="ALL",
    )
    disabled = run_precomputed_inference(
        attempt_id="mvp-tool-none",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        memory_enabled=False,
        tool_policy="NONE",
    )

    assert default_run["prediction_payload_hashes"] == explicit_all["prediction_payload_hashes"]
    disabled_root = Path(disabled["output_attempt_root"]) / "inference"
    assert (disabled_root / "traces" / "tool_trace.jsonl").read_bytes() == b""
    disabled_plan = json.loads((disabled_root / "mvp_inference_plan.json").read_bytes())
    assert disabled_plan["tool_policy"] == "NONE"
    assert disabled_plan["tool_action_order"] == []
    diagnostics = [
        json.loads(line)
        for line in (disabled_root / "diagnostics" / "window_diagnostics.jsonl").read_bytes().splitlines()
    ]
    assert all(item["accepted_actions"] == [] for item in diagnostics)


def test_semantic_manifest_and_none_policy_cross_the_worker_and_formal_evaluator(tmp_path: Path) -> None:
    receipt, _backends, _old_targets = _v1_bundle(tmp_path)
    semantic = precompute_semantic_scores(
        input_manifest_path=receipt.input_manifest_path,
        output_root=tmp_path / "semantic-worker",
        backend=FakeSemanticScoringBackend(),
    )
    target_path = tmp_path / "semantic-frame-targets.json"
    target_path.write_text(
        json.dumps(
            {
                "dataset_id": "mvp-real-assets-test",
                "experiment_config_id": "I3",
                "frame_interval": 16,
                "manifest_type": "MVP_FRAME_TARGETS_V1",
                "normal_label": 0,
                "postprocess_identity": DIRECT_B4_POSTPROCESS,
                "temporal_protocol": OFFLINE_PROTOCOL,
                "videos": [
                    {"anomaly_intervals": [], "frame_count": 32, "video_id": "mvp-video-real-reference"},
                    {
                        "anomaly_intervals": [{"end_frame": 31, "start_frame": 0}],
                        "frame_count": 32,
                        "video_id": "mvp-video-real-salient",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_asset_attempt(
        attempt_id="mvp-semantic-worker-a",
        project_root=tmp_path,
        input_manifest_path=receipt.input_manifest_path,
        target_manifest_path=target_path,
        memory_enabled=False,
        tool_policy="NONE",
        semantic_score_manifest_path=semantic.manifest_path,
        semantic_score_manifest_sha256=semantic.manifest_sha256,
    )

    assert result["status_code"] == "EVALUATION_COMPLETED"
    plan_path = tmp_path / "data" / "agentic_outputs" / "mvp" / "mvp-semantic-worker-a" / "inference" / "mvp_inference_plan.json"
    plan = json.loads(plan_path.read_bytes())
    assert plan["tool_policy"] == "NONE"
    assert plan["semantic_score_manifest_sha256"] == semantic.manifest_sha256
    assert plan["semantic_mapping_identity"] == MAPPING_IDENTITY
    diagnostic_path = (
        plan_path.parent
        / "diagnostics"
        / "windows"
        / "mvp-video-real-reference"
        / "mvp-video-real-reference-window-0000.json"
    )
    diagnostic = json.loads(diagnostic_path.read_bytes())
    vlm_lineage = next(item for item in diagnostic["evidence_artifacts"] if item["action"] == "VLM")
    assert vlm_lineage["relative_ref"] is None


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
