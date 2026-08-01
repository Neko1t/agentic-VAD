from __future__ import annotations

import sys
from types import SimpleNamespace

from scripts import download_agentic_assets as downloader


def test_models_mvp_preset_matches_real_asset_contract() -> None:
    assert downloader.PRESETS["models-mvp"] == (
        "bge-base-en-v1.5",
        "videollama3-7b",
        "easyocr-en",
        "faster-whisper-small",
    )

    assets = downloader.asset_map()
    assert all(assets[asset_id].required_now for asset_id in downloader.PRESETS["models-mvp"])
    assert assets["easyocr-en"].target == "libs/ocr/easyocr"
    assert assets["faster-whisper-small"].target == "libs/audio/faster-whisper-small"
    assert assets["faster-whisper-small"].hf_repo == "Systran/faster-whisper-small"
    assert "llama-3.1-8b-instruct" not in downloader.PRESETS["models-mvp"]


def test_asset_ready_requires_marker_and_every_required_file(tmp_path) -> None:
    asset = downloader.asset_map()["videollama3-7b"]
    marker = tmp_path / str(asset.completion_marker)
    marker.parent.mkdir(parents=True)
    marker.write_text("videollama3-7b\n", encoding="utf-8")

    assert not downloader.asset_ready(asset, tmp_path)

    for relative in asset.markers:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete")

    assert downloader.asset_ready(asset, tmp_path)


def test_asset_ready_accepts_existing_manual_dataset_directory(tmp_path) -> None:
    asset = downloader.asset_map()["ucf-crime-videos"]
    (tmp_path / asset.target).mkdir(parents=True)

    assert downloader.asset_ready(asset, tmp_path)


def test_faster_whisper_download_is_limited_to_runtime_files() -> None:
    asset = downloader.asset_map()["faster-whisper-small"]

    assert asset.hf_allow_patterns == (
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    )


def test_faster_whisper_is_ready_without_optional_preprocessor_config(tmp_path) -> None:
    asset = downloader.asset_map()["faster-whisper-small"]
    marker = tmp_path / str(asset.completion_marker)
    marker.parent.mkdir(parents=True)
    marker.write_text("faster-whisper-small\n", encoding="utf-8")
    for relative in (
        "libs/audio/faster-whisper-small/config.json",
        "libs/audio/faster-whisper-small/model.bin",
        "libs/audio/faster-whisper-small/tokenizer.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete")

    assert downloader.asset_ready(asset, tmp_path)


def test_hf_download_passes_runtime_file_filter(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def snapshot_download(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    asset = downloader.asset_map()["faster-whisper-small"]

    downloader.download_hf_mirror(asset, tmp_path, token=None)

    assert captured["allow_patterns"] == list(asset.hf_allow_patterns)


def test_easyocr_download_uses_offline_runtime_layout(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class Reader:
        def __init__(self, languages: list[str], **kwargs: object) -> None:
            captured["languages"] = languages
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=Reader))
    asset = downloader.asset_map()["easyocr-en"]
    args = SimpleNamespace(root=tmp_path, force=False)

    message = downloader.perform_download(asset, args)

    target = tmp_path / asset.target
    assert message == f"Downloaded EasyOCR weights into {target}"
    assert captured == {
        "languages": ["en"],
        "gpu": False,
        "model_storage_directory": str(target),
        "user_network_directory": str(target),
        "download_enabled": True,
    }
    assert (tmp_path / str(asset.completion_marker)).read_text(encoding="utf-8") == "easyocr-en\n"
