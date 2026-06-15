from __future__ import annotations

import argparse
import os
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass(frozen=True)
class Asset:
    asset_id: str
    title: str
    category: str
    target: str
    required_now: bool
    mode: str
    note: str
    modelscope_repo: str | None = None
    hf_repo: str | None = None
    gdrive_url: str | None = None
    manual_url: str | None = None
    gated: bool = False


ASSETS: tuple[Asset, ...] = (
    Asset(
        asset_id="bge-base-en-v1.5",
        title="Embedding model for memory retrieval",
        category="model",
        target="libs/embeddings/bge-base-en-v1.5",
        required_now=False,
        mode="download",
        note="Used by EmbeddingBuilder. The code can fall back to a deterministic local embedder, but real retrieval quality depends on this model.",
        modelscope_repo="BAAI/bge-base-en-v1.5",
        hf_repo="BAAI/bge-base-en-v1.5",
    ),
    Asset(
        asset_id="videollama3-7b",
        title="Future real VLM backend",
        category="model",
        target="libs/videollama3/VideoLLaMA3-7B",
        required_now=False,
        mode="download",
        note="Planned replacement for the current caption-json VLM path. Large download.",
        modelscope_repo="DAMO-NLP-SG/VideoLLaMA3-7B",
        hf_repo="DAMO-NLP-SG/VideoLLaMA3-7B",
    ),
    Asset(
        asset_id="llama-3.1-8b-instruct",
        title="Reasoning / scoring LLM",
        category="model",
        target="libs/llama/llama3.1-8b",
        required_now=False,
        mode="download",
        note="Referenced by the original project for first-round scoring and later reasoning expansion. May require license acceptance depending on the source.",
        modelscope_repo="LLM-Research/Meta-Llama-3.1-8B-Instruct",
        hf_repo="meta-llama/Llama-3.1-8B-Instruct",
        gated=True,
    ),
    Asset(
        asset_id="preprocessed-annotation-bundle",
        title="Project-compatible annotation bundle",
        category="support-data",
        target="data",
        required_now=True,
        mode="download",
        note="README-provided Google Drive package for project-compatible annotations and related preprocessing artifacts.",
        gdrive_url="https://drive.google.com/file/d/1jULt7PKZDTronu4eqiMwCqteKRjjVlmn/view?usp=sharing",
    ),
    Asset(
        asset_id="ucf-crime-videos",
        title="UCF-Crime raw videos",
        category="dataset",
        target="data/ucf_crime/videos",
        required_now=True,
        mode="manual",
        note="Needed if you want to reproduce frame extraction or generate new captions. The code expects extracted videos under this directory.",
        manual_url="https://visionlab.uncc.edu/download/summary/60-data/477-ucf-anomaly-detection-dataset",
    ),
    Asset(
        asset_id="xd-violence-videos",
        title="XD-Violence raw videos",
        category="dataset",
        target="data/xd_violence/videos",
        required_now=True,
        mode="manual",
        note="Needed if you want to run on XD-Violence from raw videos.",
        manual_url="https://roc-ng.github.io/XD-Violence/",
    ),
    Asset(
        asset_id="ucf-crime-captions",
        title="Precomputed UCF-Crime captions",
        category="dataset",
        target="data/ucf_crime/captions/video_llama3_json_results",
        required_now=True,
        mode="manual",
        note="Current agentic pipeline reads caption JSONs from this directory. There is no stable scriptable public link in the repo; generate them with src/video_pre_caption.py or place provided files here.",
    ),
    Asset(
        asset_id="xd-violence-captions",
        title="Precomputed XD-Violence captions",
        category="dataset",
        target="data/xd_violence/captions/video_llama3_json_results",
        required_now=True,
        mode="manual",
        note="Current agentic pipeline reads caption JSONs from this directory. Generate them with src/video_pre_caption.py or place provided files here.",
    ),
    Asset(
        asset_id="ucf-crime-baseline-scores",
        title="Baseline refined scores for UCF-Crime",
        category="dataset",
        target="data/ucf_crime/refined_scores/videollama3",
        required_now=False,
        mode="manual",
        note="Used by the workflow comparison stage. The repo README says these files are provided, but it does not expose a stable direct machine-download link.",
    ),
    Asset(
        asset_id="xd-violence-baseline-scores",
        title="Baseline refined scores for XD-Violence",
        category="dataset",
        target="data/xd_violence/refined_scores/videollama3",
        required_now=False,
        mode="manual",
        note="Used by the workflow comparison stage. Place the original pipeline scores here if available.",
    ),
)


PRESETS: dict[str, tuple[str, ...]] = {
    "list-now": tuple(asset.asset_id for asset in ASSETS if asset.required_now),
    "models-core": ("bge-base-en-v1.5",),
    "models-all": ("bge-base-en-v1.5", "videollama3-7b", "llama-3.1-8b-instruct"),
    "bootstrap": (
        "preprocessed-annotation-bundle",
        "ucf-crime-videos",
        "ucf-crime-captions",
        "ucf-crime-baseline-scores",
        "bge-base-en-v1.5",
    ),
    "all": tuple(asset.asset_id for asset in ASSETS),
}


def asset_map() -> dict[str, Asset]:
    return {asset.asset_id: asset for asset in ASSETS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download models and data assets for the agentic VAD project.",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--preset", choices=sorted(PRESETS.keys()), default="bootstrap")
    parser.add_argument("--asset", action="append", default=[])
    parser.add_argument("--source", choices=("auto", "modelscope", "hf-mirror"), default="auto")
    parser.add_argument("--list", action="store_true", help="Only print the asset plan.")
    parser.add_argument("--skip-manual", action="store_true", help="Skip manual-only assets in the execution output.")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))
    parser.add_argument("--modelscope-token", default=os.environ.get("MODELSCOPE_API_TOKEN"))
    return parser


def selected_assets(args: argparse.Namespace) -> list[Asset]:
    lookup = asset_map()
    requested = list(PRESETS[args.preset])
    requested.extend(args.asset)
    unique_ids: list[str] = []
    for asset_id in requested:
        if asset_id not in lookup:
            raise SystemExit(f"Unknown asset id: {asset_id}")
        if asset_id not in unique_ids:
            unique_ids.append(asset_id)
    return [lookup[asset_id] for asset_id in unique_ids]


def render_asset_table(assets: Iterable[Asset], root: Path) -> None:
    table = Table(title="Agentic VAD Asset Plan", show_lines=True)
    table.add_column("Asset")
    table.add_column("Category")
    table.add_column("Need Now")
    table.add_column("Mode")
    table.add_column("Target")
    table.add_column("Notes")
    for asset in assets:
        table.add_row(
            asset.asset_id,
            asset.category,
            "yes" if asset.required_now else "later",
            asset.mode,
            str(root / asset.target),
            asset.note,
        )
    console.print(table)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_modelscope(asset: Asset, dest: Path, token: str | None) -> None:
    from modelscope import snapshot_download

    if asset.modelscope_repo is None:
        raise RuntimeError(f"{asset.asset_id} does not define a ModelScope source")
    if token:
        os.environ.setdefault("MODELSCOPE_API_TOKEN", token)
    ensure_dir(dest.parent)
    snapshot_download(model_id=asset.modelscope_repo, local_dir=str(dest))


def download_hf_mirror(asset: Asset, dest: Path, token: str | None) -> None:
    from huggingface_hub import snapshot_download

    if asset.hf_repo is None:
        raise RuntimeError(f"{asset.asset_id} does not define a Hugging Face source")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    ensure_dir(dest.parent)
    snapshot_download(
        repo_id=asset.hf_repo,
        local_dir=str(dest),
        token=token,
        local_dir_use_symlinks=False,
        resume_download=True,
    )


def download_gdrive_bundle(asset: Asset, root: Path) -> None:
    import gdown

    if asset.gdrive_url is None:
        raise RuntimeError(f"{asset.asset_id} does not define a Google Drive url")
    download_dir = root / "data" / "_downloads"
    ensure_dir(download_dir)
    archive_path = download_dir / asset.asset_id
    console.print(f"[cyan]Downloading Google Drive bundle to[/cyan] {archive_path}")
    output = gdown.download(asset.gdrive_url, output=str(archive_path), quiet=False, fuzzy=True)
    if output is None:
        raise RuntimeError("gdown did not return an output path")
    extracted = try_extract_archive(Path(output), root / asset.target)
    if extracted:
        console.print(f"[green]Extracted[/green] {output} -> {root / asset.target}")
    else:
        console.print(f"[yellow]Downloaded archive[/yellow] {output}. Please inspect and extract manually if needed.")


def try_extract_archive(archive_path: Path, dest_dir: Path) -> bool:
    ensure_dir(dest_dir)
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
        return True
    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path) as tf:
            tf.extractall(dest_dir)
        return True
    return False


def perform_download(asset: Asset, args: argparse.Namespace) -> str:
    root = args.root.resolve()
    target = root / asset.target

    if asset.mode == "manual":
        ensure_dir(target)
        lines = [f"Target directory prepared: {target}"]
        if asset.manual_url:
            lines.append(f"Manual source: {asset.manual_url}")
        lines.append(asset.note)
        return "\n".join(lines)

    if asset.mode == "download" and asset.gdrive_url:
        download_gdrive_bundle(asset, root)
        return f"Downloaded support bundle into {target}"

    if asset.mode == "download":
        source = args.source
        if source == "auto":
            source = "modelscope" if asset.modelscope_repo else "hf-mirror"
        if source == "modelscope":
            download_modelscope(asset, target, args.modelscope_token)
        elif source == "hf-mirror":
            download_hf_mirror(asset, target, args.hf_token)
        else:
            raise RuntimeError(f"Unsupported source: {source}")
        return f"Downloaded to {target} via {source}"

    raise RuntimeError(f"Unsupported mode: {asset.mode}")


def print_manual_summary(assets: Iterable[Asset], root: Path) -> None:
    manual_assets = [asset for asset in assets if asset.mode == "manual"]
    if not manual_assets:
        return
    table = Table(title="Manual / External Assets", show_lines=True)
    table.add_column("Asset")
    table.add_column("Target")
    table.add_column("Source")
    table.add_column("Reason")
    for asset in manual_assets:
        table.add_row(
            asset.asset_id,
            str(root / asset.target),
            asset.manual_url or "No stable direct link in repo",
            asset.note,
        )
    console.print(table)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.root = args.root.resolve()

    assets = selected_assets(args)
    console.print(
        Panel(
            Text.from_markup(
                "[bold cyan]Agentic VAD asset downloader[/bold cyan]\n"
                "Default strategy: use ModelScope first for models, and fall back to hf-mirror only when requested."
            )
        )
    )
    render_asset_table(assets, args.root)
    if args.list:
        print_manual_summary(assets, args.root)
        return 0

    for index, asset in enumerate(assets, start=1):
        if asset.mode == "manual" and args.skip_manual:
            console.print(f"[yellow][{index}/{len(assets)}] Skip manual asset[/yellow] {asset.asset_id}")
            continue
        console.rule(f"[{index}/{len(assets)}] {asset.asset_id}")
        if asset.gated:
            console.print(
                "[yellow]Note:[/yellow] This asset may require upstream license acceptance or login. "
                "If the download fails, accept the license on the source platform first."
            )
        try:
            message = perform_download(asset, args)
        except Exception as exc:
            console.print(f"[red]Failed[/red] {asset.asset_id}: {exc}")
            return 1
        console.print(f"[green]Done[/green] {asset.asset_id}: {message}")

    print_manual_summary(assets, args.root)
    console.print("[bold green]All requested actions finished.[/bold green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
