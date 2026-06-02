from __future__ import annotations

import json
from pathlib import Path
from typing import List

import typer

from src.agents.perception_agent import PerceptionAgent
from src.agents.story_memory_agent import StoryMemoryAgent
from src.core.config import PipelineConfig
from src.core.schemas import CaseMemoryRecord, DecisionReport, DecisionSegment, ObservationCard, TimeSpan, WindowInput
from src.data.video_record import VideoRecord
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.pattern_store import PatternMemoryStore
from src.tools.audio_tool import AudioTool
from src.tools.ocr_tool import OCRTool
from src.tools.rag_tool import RAGTool
from src.tools.score_tool import ScoreTool
from src.tools.vlm_tool import VLMTool

app = typer.Typer(add_completion=False, help="Run the agentic VAD pipeline on an annotated dataset split.")


def _load_video_records(root_path: Path, annotation_file_path: Path) -> List[VideoRecord]:
    with annotation_file_path.open("r", encoding="utf-8") as handle:
        return [VideoRecord(line.strip().split(), str(root_path)) for line in handle if line.strip()]


def _build_window_inputs(video: VideoRecord, frame_interval: int) -> List[WindowInput]:
    windows: List[WindowInput] = []
    for index, start_frame in enumerate(range(video.start_frame, video.end_frame + 1, frame_interval)):
        end_frame = min(start_frame + frame_interval - 1, video.end_frame)
        span = TimeSpan(start_frame=start_frame, end_frame=end_frame)
        windows.append(
            WindowInput(
                video_id=Path(video.path).stem,
                video_path=video.path,
                window_id=f"{Path(video.path).stem}_{index:04d}",
                time_span=span,
                frame_indices=list(range(start_frame, end_frame + 1)),
            )
        )
    return windows


def _build_case_record(episode, state, score_threshold: float) -> CaseMemoryRecord | None:
    score = max(episode.score_story, episode.score_memory_adjusted)
    if score < score_threshold:
        return None
    entities = list(dict.fromkeys(state.active_entities))[:10]
    evidence_tags = [token.strip() for token in episode.action_sequence.split("->") if token.strip()]
    return CaseMemoryRecord(
        case_id=f"{episode.video_id}_{episode.segment_span.start_frame}_{episode.segment_span.end_frame}",
        video_id=episode.video_id,
        time_span=episode.segment_span,
        label="high-risk" if score >= 7.5 else "candidate",
        risk_score=score,
        episode_summary=episode.story_text,
        action_sequence=episode.action_sequence,
        key_entities=entities,
        scene_type=state.current_scene,
        evidence_tags=evidence_tags,
        outcome="auto-generated from inference",
        embedding_text=" | ".join(
            [
                episode.action_sequence,
                state.current_scene,
                " ".join(evidence_tags),
                episode.story_text,
            ]
        ),
        provisional=score < 8.0,
    )


def _build_report(
    video_id: str,
    observations: List[ObservationCard],
    episodes,
    threshold: float,
) -> DecisionReport:
    abnormal_segments: List[DecisionSegment] = []
    segment_scores: List[float] = []
    retrieved_cases: List[str] = []
    matched_patterns: List[str] = []
    evidence: List[str] = []
    for observation, episode in zip(observations, episodes):
        score = max(observation.score_weighted, episode.score_memory_adjusted)
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
        retrieved_cases.extend(episode.retrieved_case_ids)
        matched_patterns.extend(episode.matched_pattern_ids)
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


@app.command()
def main(
    root_path: Path = typer.Option(..., exists=True, file_okay=False),
    annotation_file_path: Path = typer.Option(..., exists=True, dir_okay=False),
    captions_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("./data/agentic_outputs")),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    frame_interval: int = typer.Option(16, min=1),
    rolling_window_size: int = typer.Option(4, min=1),
    use_audio: bool = typer.Option(False),
    use_ocr: bool = typer.Option(False),
    top_k: int = typer.Option(5, min=1),
) -> None:
    config = PipelineConfig(
        root_path=root_path,
        annotation_file_path=annotation_file_path,
        captions_dir=captions_dir,
        output_dir=output_dir,
        frame_interval=frame_interval,
        rolling_window_size=rolling_window_size,
        use_audio=use_audio,
        use_ocr=use_ocr,
    )
    config.memory.storage_dir = memory_dir
    config.memory.top_k = top_k
    config.ensure_directories()

    embedding_builder = EmbeddingBuilder(model_name=config.memory.embedding_model_name)
    case_store = CaseMemoryStore(
        storage_dir=config.memory.storage_dir,
        collection_name=config.memory.case_collection_name,
        provisional_collection_name=config.memory.provisional_collection_name,
        embedding_builder=embedding_builder,
        use_chroma=config.memory.use_chroma,
    )
    pattern_store = PatternMemoryStore(config.memory.storage_dir / config.memory.pattern_file_name)
    rag_tool = RAGTool(case_store=case_store, pattern_store=pattern_store)
    score_tool = ScoreTool(config.scoring)
    perception_agent = PerceptionAgent(
        vlm_tool=VLMTool(captions_dir=config.captions_dir),
        audio_tool=AudioTool(enabled=config.use_audio, backend_name=config.audio_backend),
        ocr_tool=OCRTool(enabled=config.use_ocr, backend_name=config.ocr_backend),
        score_tool=score_tool,
    )
    story_agent = StoryMemoryAgent(
        rag_tool=rag_tool,
        score_tool=score_tool,
        rolling_window_size=config.rolling_window_size,
        top_k=config.memory.top_k,
    )

    video_records = _load_video_records(config.root_path, config.annotation_file_path)
    for video in video_records:
        windows = _build_window_inputs(video, config.frame_interval)
        if not windows:
            continue
        observations: List[ObservationCard] = []
        episodes = []
        state = story_agent.initialize_state(Path(video.path).stem)
        for window in windows:
            observation = perception_agent.process_window(window)
            observations.append(observation)
            episode, state = story_agent.summarize_episode(state, observations[-config.rolling_window_size :])
            episodes.append(episode)
            case_record = _build_case_record(episode, state, config.scoring.provisional_score_threshold)
            if case_record is not None:
                rag_tool.rag_store(case_record)
        report = _build_report(Path(video.path).stem, observations, episodes, config.scoring.segment_score_threshold)
        report_dir = config.output_dir / "reports"
        observation_dir = config.output_dir / "observations"
        episode_dir = config.output_dir / "episodes"
        report_dir.mkdir(parents=True, exist_ok=True)
        observation_dir.mkdir(parents=True, exist_ok=True)
        episode_dir.mkdir(parents=True, exist_ok=True)
        with (report_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
            json.dump(report.model_dump(mode="json"), handle, indent=2)
        with (observation_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
            json.dump([item.model_dump(mode="json") for item in observations], handle, indent=2)
        with (episode_dir / f"{report.video_id}.json").open("w", encoding="utf-8") as handle:
            json.dump([item.model_dump(mode="json") for item in episodes], handle, indent=2)


if __name__ == "__main__":
    app()
