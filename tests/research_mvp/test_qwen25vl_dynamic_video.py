from __future__ import annotations

import json
from pathlib import Path

from src.research_mvp.adapters.qwen25vl_dynamic_video import (
    DYNAMIC_VIDEO_ADAPTER_IDENTITY,
    DYNAMIC_VIDEO_MANIFEST_TYPE,
    DeterministicDynamicVideoBackend,
    precompute_dynamic_video_events,
)
from src.research_mvp.artifacts.hashes import file_sha256
from src.research_mvp.codec import loads

from .test_real_asset_pipeline import _visual_bundle


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_dynamic_video_precompute_persists_qwen_io_and_observations(tmp_path: Path) -> None:
    bundle, _backend, source_path = _visual_bundle(tmp_path)
    output_root = tmp_path / "dynamic-qwen"

    receipt = precompute_dynamic_video_events(
        input_manifest_path=bundle.input_manifest_path,
        source_manifest_path=source_path,
        asset_root=tmp_path / "assets",
        output_root=output_root,
        backend=DeterministicDynamicVideoBackend(),
    )

    manifest = loads(receipt.manifest_path.read_bytes())
    assert manifest["manifest_type"] == DYNAMIC_VIDEO_MANIFEST_TYPE
    assert manifest["adapter_identity"] == DYNAMIC_VIDEO_ADAPTER_IDENTITY
    assert manifest["backend_identity"] == DeterministicDynamicVideoBackend.identity
    assert manifest["input_manifest_sha256"] == file_sha256(bundle.input_manifest_path)
    assert receipt.observation_count == manifest["observation_count"] == 4
    assert receipt.parse_success_count == manifest["parse_success_count"] == 4

    io_path = output_root / manifest["model_io"]["relative_ref"]
    io_rows = _jsonl(io_path)
    assert len(io_rows) == 4
    assert all(row["input_segment_hash"] for row in io_rows)
    assert all(row["raw_output_ref"].startswith("raw_model_outputs/") for row in io_rows)
    assert all((output_root / row["raw_output_ref"]).is_file() for row in io_rows)
    assert all(row["parse_status"] == "PARSED" for row in io_rows)

    observation_file = manifest["observation_files"][0]
    observation_rows = _jsonl(output_root / observation_file["relative_ref"])
    assert observation_rows[0]["observation"]["events"][0]["event_type"] == "stable_scene"
    assert observation_rows[0]["raw_output_sha256"] == file_sha256(output_root / observation_rows[0]["raw_output_ref"])


def test_dynamic_video_cli_exposes_precompute_command() -> None:
    from src.research_mvp.cli import main

    try:
        main(["precompute-dynamic-video-events", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
