from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters.real_assets import MvpRealModelConfig, inspect_real_assets, precompute_asset_bundle
from .failures import MvpFailure
from .launcher import compare_frozen_attempts


def _add_real_asset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--caption-model", default="libs/videollama3/VideoLLaMA3-7B")
    parser.add_argument("--ocr-model", default="libs/ocr/easyocr")
    parser.add_argument("--audio-model", default="libs/audio/faster-whisper-small")
    parser.add_argument("--embedding-model", default="libs/embeddings/bge-base-en-v1.5")
    parser.add_argument("--gpu-device", required=True)


def _real_model_config(args: argparse.Namespace) -> MvpRealModelConfig:
    return MvpRealModelConfig(
        caption_model=Path(args.caption_model),
        ocr_model=Path(args.ocr_model),
        audio_model=Path(args.audio_model),
        embedding_model=Path(args.embedding_model),
        gpu_device=str(args.gpu_device),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_mvp.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare_parser = subparsers.add_parser("compare-frozen")
    compare_parser.add_argument("--left", required=True)
    compare_parser.add_argument("--right", required=True)
    inspect_parser = subparsers.add_parser("inspect-real-assets")
    _add_real_asset_arguments(inspect_parser)
    precompute_parser = subparsers.add_parser("precompute-real-assets")
    _add_real_asset_arguments(precompute_parser)
    precompute_parser.add_argument("--bundle-id", required=True)
    precompute_parser.add_argument("--bundle-root")
    args = parser.parse_args(argv)
    try:
        if args.command == "compare-frozen":
            result = compare_frozen_attempts(Path.cwd(), args.left, args.right)
        elif args.command == "inspect-real-assets":
            result = inspect_real_assets(
                Path(args.source_manifest),
                Path(args.asset_root),
                _real_model_config(args),
            )
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0 if result["status_code"] == "ASSET_READY" else 3
        else:
            bundle_root = (
                Path(args.bundle_root)
                if args.bundle_root
                else Path.cwd() / "data" / "agentic_outputs" / "mvp" / "precomputed" / args.bundle_id
            )
            receipt = precompute_asset_bundle(
                bundle_id=args.bundle_id,
                source_manifest_path=Path(args.source_manifest),
                asset_root=Path(args.asset_root),
                bundle_root=bundle_root,
                model_config=_real_model_config(args),
            )
            result = {
                "bundle_id": receipt.bundle_id,
                "bundle_manifest_path": str(receipt.bundle_manifest_path.resolve()),
                "bundle_manifest_sha256": receipt.bundle_manifest_sha256,
                "input_manifest_path": str(receipt.input_manifest_path.resolve()),
                "input_manifest_sha256": receipt.input_manifest_sha256,
                "status_code": receipt.status_code,
            }
    except MvpFailure as exc:
        print(json.dumps({"failure_code": exc.code, "severity": exc.severity}, separators=(",", ":")))
        return 3 if exc.code == "ASSET_NOT_RUN" else 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
