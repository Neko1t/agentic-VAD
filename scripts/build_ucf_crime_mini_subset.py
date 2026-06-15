from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()

DEFAULT_VIDEOS = (
    "Abuse028_x264",
    "Abuse030_x264",
    "Arrest001_x264",
    "Arson009_x264",
    "Arson010_x264",
)


@dataclass(frozen=True)
class MiniSubsetConfig:
    source_root: Path
    target_root: Path
    videos: tuple[str, ...]
    copy_videos: bool
    extract_frames: bool
    force: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a small UCF-Crime subset for agentic VAD smoke experiments.")
    parser.add_argument("--source-root", type=Path, default=Path("./data/ucf_crime"))
    parser.add_argument("--target-root", type=Path, default=Path("./data/ucf_crime_mini"))
    parser.add_argument("--video", action="append", default=[], help="Video basename to include. Can be repeated.")
    parser.add_argument("--copy-videos", action="store_true", default=True, help="Copy source videos into the mini subset.")
    parser.add_argument("--no-copy-videos", action="store_false", dest="copy_videos")
    parser.add_argument("--extract-frames", action="store_true", default=True, help="Extract frames from copied videos.")
    parser.add_argument("--no-extract-frames", action="store_false", dest="extract_frames")
    parser.add_argument("--force", action="store_true", help="Overwrite existing subset files and re-extract frames.")
    return parser


def resolve_videos(requested: list[str]) -> tuple[str, ...]:
    if not requested:
        return DEFAULT_VIDEOS
    unique: list[str] = []
    for item in requested:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def render_plan(config: MiniSubsetConfig) -> None:
    table = Table(title="UCF-Crime Mini Subset Plan", show_lines=True)
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Source root", str(config.source_root.resolve()))
    table.add_row("Target root", str(config.target_root.resolve()))
    table.add_row("Videos", ", ".join(config.videos))
    table.add_row("Copy videos", str(config.copy_videos))
    table.add_row("Extract frames", str(config.extract_frames))
    table.add_row("Force", str(config.force))
    console.print(table)


def ensure_layout(target_root: Path) -> None:
    for relative in (
        "annotations",
        "captions/video_llama3_json_results",
        "refined_scores/videollama3",
        "videos",
        "frames",
    ):
        (target_root / relative).mkdir(parents=True, exist_ok=True)


def filter_lines(source_file: Path, target_file: Path, videos: tuple[str, ...], force: bool) -> tuple[int, int]:
    selected = []
    with source_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split()[0]
            if name in videos:
                selected.append(line)
    if target_file.exists() and not force:
        existing = target_file.read_text(encoding="utf-8").splitlines()
        if len(existing) == len(selected):
            return len(selected), 0
    target_file.write_text("".join(selected), encoding="utf-8")
    return len(selected), len(selected)


def copy_json_assets(
    source_dir: Path,
    target_dir: Path,
    videos: tuple[str, ...],
    force: bool,
) -> tuple[int, int]:
    found = 0
    copied = 0
    for video in videos:
        source_file = source_dir / f"{video}.json"
        if not source_file.exists():
            console.print(f"[yellow]Missing[/yellow] {source_file}")
            continue
        found += 1
        target_file = target_dir / source_file.name
        if target_file.exists() and not force:
            continue
        shutil.copy2(source_file, target_file)
        copied += 1
    return found, copied


def resolve_video_file(videos_dir: Path, video_id: str) -> Path | None:
    for extension in (".mp4", ".avi", ".mov", ".mkv"):
        candidate = videos_dir / f"{video_id}{extension}"
        if candidate.exists():
            return candidate
    return None


def copy_video_assets(
    source_videos_dir: Path,
    target_videos_dir: Path,
    videos: tuple[str, ...],
    force: bool,
) -> tuple[int, int]:
    found = 0
    copied = 0
    for video in videos:
        source_file = resolve_video_file(source_videos_dir, video)
        if source_file is None:
            console.print(f"[yellow]Missing video[/yellow] {video}")
            continue
        found += 1
        target_file = target_videos_dir / source_file.name
        if target_file.exists() and not force:
            continue
        shutil.copy2(source_file, target_file)
        copied += 1
    return found, copied


def count_existing_frames(frames_dir: Path) -> int:
    if not frames_dir.exists():
        return 0
    return len(list(frames_dir.glob("*.jpg")))


def extract_video_frames(video_path: Path, frames_root: Path, force: bool) -> tuple[int, bool]:
    video_name = video_path.stem
    output_dir = frames_root / video_name
    if output_dir.exists() and not force:
        existing = count_existing_frames(output_dir)
        if existing > 0:
            return existing, False
    output_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for frame_file in output_dir.glob("*.jpg"):
            frame_file.unlink()

    cap = cv2.VideoCapture(str(video_path))
    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frame_path = output_dir / f"{frame_count:06d}.jpg"
        cv2.imwrite(str(frame_path), frame)
        frame_count += 1
    cap.release()
    return frame_count, True


def main() -> int:
    args = build_parser().parse_args()
    config = MiniSubsetConfig(
        source_root=args.source_root.resolve(),
        target_root=args.target_root.resolve(),
        videos=resolve_videos(args.video),
        copy_videos=args.copy_videos,
        extract_frames=args.extract_frames,
        force=args.force,
    )

    console.print(
        Panel(
            "Build a compact UCF-Crime subset for fast agentic VAD validation.\n"
            "The script copies annotations, captions, baseline scores, optional videos, and optional frames.",
            title="Mini Subset Builder",
        )
    )
    render_plan(config)
    ensure_layout(config.target_root)

    source_annotations = config.source_root / "annotations"
    source_captions = config.source_root / "captions" / "video_llama3_json_results"
    source_scores = config.source_root / "refined_scores" / "videollama3"
    source_videos = config.source_root / "videos"

    target_annotations = config.target_root / "annotations"
    target_captions = config.target_root / "captions" / "video_llama3_json_results"
    target_scores = config.target_root / "refined_scores" / "videollama3"
    target_videos = config.target_root / "videos"
    target_frames = config.target_root / "frames"

    results: dict[str, str] = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("subset build", total=5)

        selected, written = filter_lines(
            source_annotations / "test.txt",
            target_annotations / "test.txt",
            config.videos,
            config.force,
        )
        results["test.txt"] = f"selected={selected}, written={written}"
        progress.advance(task)

        selected, written = filter_lines(
            source_annotations / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
            target_annotations / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
            config.videos,
            config.force,
        )
        results["temporal annotations"] = f"selected={selected}, written={written}"
        progress.advance(task)

        found, copied = copy_json_assets(source_captions, target_captions, config.videos, config.force)
        results["captions"] = f"found={found}, copied={copied}"
        progress.advance(task)

        found, copied = copy_json_assets(source_scores, target_scores, config.videos, config.force)
        results["baseline scores"] = f"found={found}, copied={copied}"
        progress.advance(task)

        if config.copy_videos:
            found, copied = copy_video_assets(source_videos, target_videos, config.videos, config.force)
            results["videos"] = f"found={found}, copied={copied}"
        else:
            results["videos"] = "skipped by flag"
        progress.advance(task)

    if config.copy_videos and config.extract_frames:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("frame extraction", total=len(config.videos))
            extracted = []
            for video in config.videos:
                video_path = resolve_video_file(target_videos, video)
                if video_path is None:
                    extracted.append(f"{video}: missing video")
                    progress.advance(task)
                    continue
                frame_count, wrote = extract_video_frames(video_path, target_frames, config.force)
                status = "extracted" if wrote else "skipped"
                extracted.append(f"{video}: {status}, frames={frame_count}")
                progress.advance(task)
            results["frames"] = "; ".join(extracted)
    else:
        results["frames"] = "skipped"

    summary = Table(title="Mini Subset Result", show_lines=True)
    summary.add_column("Step")
    summary.add_column("Result")
    for key, value in results.items():
        summary.add_row(key, value)
    console.print(summary)
    console.print(f"[bold green]Subset ready:[/bold green] {config.target_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
