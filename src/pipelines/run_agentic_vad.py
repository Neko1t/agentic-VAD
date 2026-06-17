from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import typer

from src.agents.perception_agent import PerceptionAgent
from src.agents.story_memory_agent import StoryMemoryAgent
from src.core.config import PipelineConfig
from src.core.schemas import (
    DecisionReport,
    DecisionSegment,
    MemoryWriteDecision,
    ObservationCard,
    RunMode,
    StoryMemoryInput,
    StoryMemoryResult,
    TimeSpan,
    WindowInput,
)
from src.data.video_record import VideoRecord
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.policy import MemoryPolicy
from src.memory.pattern_store import PatternMemoryStore
from src.memory.session_store import SessionMemoryStore
from src.runtime.device import activate_gpu_device
from src.runtime.progress import NullProgressReporter, ProgressEvent, ProgressReporter
from src.tools.audio_tool import AudioTool
from src.tools.ocr_tool import OCRTool
from src.tools.rag_tool import RAGTool
from src.tools.score_tool import ScoreTool
from src.tools.vlm_tool import VLMTool, VideoLLaMABackend

app = typer.Typer(add_completion=False, help="Run the agentic VAD pipeline on an annotated dataset split.")


def _load_video_records(root_path: Path, annotation_file_path: Path) -> List[VideoRecord]:
    with annotation_file_path.open("r", encoding="utf-8") as handle:
        return [VideoRecord(line.strip().split(), str(root_path)) for line in handle if line.strip()]


def _resolve_frame_paths(root_path: Path, video: VideoRecord, start_frame: int, end_frame: int) -> List[str]:
    frame_dir = root_path / Path(video.path).stem
    if not frame_dir.exists() or not frame_dir.is_dir():
        return []
    frame_paths: List[str] = []
    for frame_index in range(start_frame, end_frame + 1):
        for name in (f"{frame_index:06d}.jpg", f"{frame_index:06d}.png", f"{frame_index}.jpg", f"{frame_index}.png"):
            candidate = frame_dir / name
            if candidate.exists():
                frame_paths.append(str(candidate))
                break
    return frame_paths


def _resolve_video_path(video: VideoRecord, video_root_path: Path | None) -> str:
    if video_root_path is None:
        return video.path
    stem = Path(video.path).stem
    for extension in (".mp4", ".avi", ".mov", ".mkv"):
        candidate = video_root_path / f"{stem}{extension}"
        if candidate.exists():
            return str(candidate)
    return str(video_root_path / stem)


def _build_window_inputs(
    video: VideoRecord,
    frame_interval: int,
    *,
    root_path: Path,
    video_root_path: Path | None,
) -> List[WindowInput]:
    windows: List[WindowInput] = []
    resolved_video_path = _resolve_video_path(video, video_root_path)
    for index, start_frame in enumerate(range(video.start_frame, video.end_frame + 1, frame_interval)):
        end_frame = min(start_frame + frame_interval - 1, video.end_frame)
        span = TimeSpan(start_frame=start_frame, end_frame=end_frame)
        windows.append(
            WindowInput(
                video_id=Path(video.path).stem,
                video_path=resolved_video_path,
                window_id=f"{Path(video.path).stem}_{index:04d}",
                time_span=span,
                frame_indices=list(range(start_frame, end_frame + 1)),
                frame_paths=_resolve_frame_paths(root_path, video, start_frame, end_frame),
            )
        )
    return windows


def _build_report(
    video_id: str,
    observations: List[ObservationCard],
    story_results: List[StoryMemoryResult],
    threshold: float,
) -> DecisionReport:
    abnormal_segments: List[DecisionSegment] = []
    segment_scores: List[float] = []
    retrieved_cases: List[str] = []
    matched_patterns: List[str] = []
    evidence: List[str] = []
    for observation, story_result in zip(observations, story_results):
        episode = story_result.episode
        score = story_result.calibration.final_score
        segment_scores.append(score)
        if score >= threshold:
            abnormal_segments.append(
                DecisionSegment(
                    segment_span=episode.segment_span,
                    score=score,
                    explanation=episode.story_text,
                )
            )
            evidence.append(observation.vision_caption)
        retrieved_cases.extend(story_result.episode.retrieved_case_ids)
        matched_patterns.extend(story_result.episode.matched_pattern_ids)
    video_level_score = sum(segment_scores) / len(segment_scores) if segment_scores else 0.0
    return DecisionReport(
        video_id=video_id,
        abnormal_segments=abnormal_segments,
        segment_scores=segment_scores,
        video_level_score=video_level_score,
        top_evidence=evidence[:5],
        retrieved_cases=list(dict.fromkeys(retrieved_cases)),
        matched_patterns=list(dict.fromkeys(matched_patterns)),
        final_explanation=f"Processed {len(observations)} windows and found {len(abnormal_segments)} suspicious segments.",
    )


def _build_eval_scores(
    observations: List[ObservationCard],
    story_results: List[StoryMemoryResult],
    normalize_to_unit_interval: bool = True,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for observation, story_result in zip(observations, story_results):
        frame_idx = observation.time_span.start_frame
        score = float(story_result.calibration.final_score)
        if normalize_to_unit_interval:
            score = score / 10.0
        scores[str(frame_idx)] = round(score, 4)
    return scores


def _build_vlm_tool(config: PipelineConfig) -> tuple[VLMTool, str]:
    if config.use_vlm:
        if config.video_root_path is None:
            raise ValueError("video_root_path is required when use_vlm=True")
        backend = VideoLLaMABackend(
            video_root=config.video_root_path,
            model_path=config.vlm_model_path,
            runtime_device=config.runtime_device,
        )
        return VLMTool(backend=backend), backend.name
    return VLMTool(captions_dir=config.captions_dir), "caption"


def run_pipeline(
    *,
    root_path: Path,
    annotation_file_path: Path,
    captions_dir: Path,
    output_dir: Path = Path("./data/agentic_outputs"),
    memory_dir: Path = Path("./data/agentic_memory"),
    gpu_device: str,
    frame_interval: int = 16,
    rolling_window_size: int = 4,
    use_audio: bool = False,
    use_ocr: bool = False,
    top_k: int = 5,
    run_mode: RunMode = RunMode.ONLINE_INFERENCE,
    use_chroma: bool = True,
    export_eval_scores: bool = True,
    use_vlm: bool = False,
    video_root_path: Path | None = None,
    vlm_model_path: Path | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    reporter = progress_reporter or NullProgressReporter()
    device_binding = activate_gpu_device(gpu_device)
    config = PipelineConfig(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        run_mode=run_mode,
        gpu_device=device_binding.requested_gpu,
        runtime_device=device_binding.runtime_device,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )
    config.memory.storage_dir = memory_dir
    config.memory.top_k = top_k
    config.memory.use_chroma = use_chroma
    config.ensure_directories()

    embedding_builder = EmbeddingBuilder(
        model_name=config.memory.embedding_model_name,
        device=config.runtime_device,
    )
    case_store = CaseMemoryStore(
        storage_dir=config.memory.storage_dir,
        collection_name=config.memory.case_collection_name,
        provisional_collection_name=config.memory.provisional_collection_name,
        embedding_builder=embedding_builder,
        use_chroma=config.memory.use_chroma,
    )
    pattern_store = PatternMemoryStore(config.memory.storage_dir / config.memory.pattern_file_name)
    session_store = SessionMemoryStore(embedding_builder) if config.memory.use_session_memory else None
    rag_tool = RAGTool(case_store=case_store, pattern_store=pattern_store, session_store=session_store)
    score_tool = ScoreTool(config.scoring)
    vlm_tool, vlm_mode = _build_vlm_tool(config)
    perception_agent = PerceptionAgent(
        vlm_tool=vlm_tool,
        audio_tool=AudioTool(enabled=config.use_audio, backend_name=config.audio_backend),
        ocr_tool=OCRTool(enabled=config.use_ocr, backend_name=config.ocr_backend),
        score_tool=score_tool,
        progress_callback=reporter.emit,
    )
    story_agent = StoryMemoryAgent(
        rag_tool=rag_tool,
        score_tool=score_tool,
        memory_policy=MemoryPolicy(write_threshold=config.scoring.provisional_score_threshold),
        rolling_window_size=config.rolling_window_size,
        top_k=config.memory.top_k,
        progress_callback=reporter.emit,
    )

    try:
        video_records = _load_video_records(config.root_path, config.annotation_file_path)
        prepared = [
            (
                video,
                _build_window_inputs(
                    video,
                    config.frame_interval,
                    root_path=config.root_path,
                    video_root_path=config.video_root_path,
                ),
            )
            for video in video_records
        ]
        total_windows = sum(len(windows) for _, windows in prepared)
        processed_windows = 0
        processed_videos = 0

        reporter.emit(
            ProgressEvent(
                stage="pipeline",
                event="run_start",
                completed=0,
                total=max(1, total_windows),
                message=f"starting {len(prepared)} videos",
            )
        )

        report_dir = config.output_dir / "reports"
        observation_dir = config.output_dir / "observations"
        episode_dir = config.output_dir / "episodes"
        story_result_dir = config.output_dir / "story_results"
        score_dir = config.output_dir / "scores"
        report_dir.mkdir(parents=True, exist_ok=True)
        observation_dir.mkdir(parents=True, exist_ok=True)
        episode_dir.mkdir(parents=True, exist_ok=True)
        story_result_dir.mkdir(parents=True, exist_ok=True)
        if export_eval_scores:
            score_dir.mkdir(parents=True, exist_ok=True)

        for video_index, (video, windows) in enumerate(prepared, start=1):
            if not windows:
                continue
            video_id = Path(video.path).stem
            reporter.emit(
                ProgressEvent(
                    stage="pipeline",
                    event="video_start",
                    completed=processed_windows,
                    total=max(1, total_windows),
                    video_id=video_id,
                    message=f"video {video_index}/{len(prepared)}",
                )
            )
            observations: List[ObservationCard] = []
            episodes = []
            story_results: List[StoryMemoryResult] = []
            state = story_agent.initialize_state(video_id)
            for window_index, window in enumerate(windows, start=1):
                reporter.emit(
                    ProgressEvent(
                        stage="pipeline",
                        event="window_start",
                        completed=processed_windows,
                        total=max(1, total_windows),
                        video_id=video_id,
                        window_id=window.window_id,
                        message=f"window {window_index}/{len(windows)}",
                    )
                )
                observation = perception_agent.process_window(window)
                observations.append(observation)
                story_input = StoryMemoryInput(
                    video_id=window.video_id,
                    state=state,
                    recent_observations=observations[-config.rolling_window_size :],
                    top_k=config.memory.top_k,
                    run_mode=config.run_mode,
                )
                story_result = story_agent.process(story_input)
                state = story_result.state
                episodes.append(story_result.episode)
                story_results.append(story_result)
                if (
                    story_result.memory_event is not None
                    and story_result.memory_event.decision == MemoryWriteDecision.WRITE
                    and story_result.memory_event.case_record is not None
                ):
                    rag_tool.rag_store_session(story_result.memory_event.case_record)
                    rag_tool.rag_store(story_result.memory_event.case_record)
                processed_windows += 1
                reporter.emit(
                    ProgressEvent(
                        stage="pipeline",
                        event="window_end",
                        completed=processed_windows,
                        total=max(1, total_windows),
                        video_id=video_id,
                        window_id=window.window_id,
                        message=f"window {window_index}/{len(windows)} done",
                    )
                )
            report = _build_report(video_id, observations, story_results, config.scoring.segment_score_threshold)
            with (report_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
                json.dump(report.model_dump(mode="json"), handle, indent=2)
            with (observation_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
                json.dump([item.model_dump(mode="json") for item in observations], handle, indent=2)
            with (episode_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
                json.dump([item.model_dump(mode="json") for item in episodes], handle, indent=2)
            with (story_result_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
                json.dump([item.model_dump(mode="json") for item in story_results], handle, indent=2)
            if export_eval_scores:
                eval_scores = _build_eval_scores(observations, story_results)
                with (score_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
                    json.dump(eval_scores, handle, indent=4)
            processed_videos += 1
            reporter.emit(
                ProgressEvent(
                    stage="pipeline",
                    event="video_end",
                    completed=processed_windows,
                    total=max(1, total_windows),
                    video_id=video_id,
                    message=f"saved outputs for {video_id}",
                )
            )

        summary = {
            "videos_total": len(prepared),
            "videos_processed": processed_videos,
            "windows_total": total_windows,
            "windows_processed": processed_windows,
            "output_dir": str(config.output_dir),
            "memory_dir": str(config.memory.storage_dir),
            "reports_dir": str(report_dir),
            "observations_dir": str(observation_dir),
            "episodes_dir": str(episode_dir),
            "story_results_dir": str(story_result_dir),
            "scores_dir": str(score_dir) if export_eval_scores else None,
            "export_eval_scores": export_eval_scores,
            "gpu_device": config.gpu_device,
            "runtime_device": config.runtime_device,
            "use_vlm": config.use_vlm,
            "vlm_mode": vlm_mode,
            "video_root_path": str(config.video_root_path) if config.video_root_path else None,
            "vlm_model_path": str(config.vlm_model_path) if config.vlm_model_path else None,
        }
        reporter.emit(
            ProgressEvent(
                stage="pipeline",
                event="run_complete",
                completed=max(1, total_windows) if total_windows else 1,
                total=max(1, total_windows),
                message=f"completed {processed_videos} videos",
            )
        )
        return summary
    finally:
        close = getattr(vlm_tool, "close", None)
        if callable(close):
            close()


@app.command()
def main(
    root_path: Path = typer.Option(..., exists=True, file_okay=False),
    annotation_file_path: Path = typer.Option(..., exists=True, dir_okay=False),
    captions_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    gpu_device: str = typer.Option(..., help="Physical GPU index to reserve, for example 0 or 1."),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
    run_mode: RunMode = typer.Option(RunMode.ONLINE_INFERENCE),
    use_chroma: bool = typer.Option(True),
    export_eval_scores: bool = typer.Option(True),
    use_vlm: bool = typer.Option(False, "--use-vlm/--no-use-vlm"),
    video_root_path: Path | None = typer.Option(None),
    vlm_model_path: Path | None = typer.Option(None),
) -> None:
    run_pipeline(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        memory_dir=memory_dir,
        gpu_device=gpu_device,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
        top_k=top_k,
        run_mode=run_mode,
        use_chroma=use_chroma,
        export_eval_scores=export_eval_scores,
        use_vlm=use_vlm,
        video_root_path=video_root_path,
        vlm_model_path=vlm_model_path,
    )


if __name__ == "__main__":
    app()
