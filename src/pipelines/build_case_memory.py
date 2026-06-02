from __future__ import annotations

import json
from pathlib import Path

import typer

from src.core.config import MemoryConfig
from src.core.schemas import CaseMemoryRecord
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder

app = typer.Typer(add_completion=False, help="Build or refresh the case memory store from episode outputs.")


@app.command()
def main(
    episodes_dir: Path = typer.Option(..., exists=True, file_okay=False),
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    min_score: float = typer.Option(6.5, min=0.0, max=10.0),
) -> None:
    config = MemoryConfig(storage_dir=memory_dir)
    store = CaseMemoryStore(
        storage_dir=config.storage_dir,
        collection_name=config.case_collection_name,
        provisional_collection_name=config.provisional_collection_name,
        embedding_builder=EmbeddingBuilder(model_name=config.embedding_model_name),
        use_chroma=config.use_chroma,
    )
    imported = 0
    for episode_file in sorted(episodes_dir.glob("*.json")):
        with episode_file.open("r", encoding="utf-8") as handle:
            episodes = json.load(handle)
        for episode in episodes:
            score = max(float(episode.get("score_story", 0.0)), float(episode.get("score_memory_adjusted", 0.0)))
            if score < min_score:
                continue
            span = episode["segment_span"]
            case = CaseMemoryRecord(
                case_id=f"{episode['video_id']}_{span['start_frame']}_{span['end_frame']}",
                video_id=episode["video_id"],
                time_span=span,
                label="imported",
                risk_score=score,
                episode_summary=episode["story_text"],
                action_sequence=episode["action_sequence"],
                key_entities=[],
                scene_type="",
                evidence_tags=[token.strip() for token in episode["action_sequence"].split("->") if token.strip()],
                outcome="imported from episode summaries",
                embedding_text=f"{episode['action_sequence']} | {episode['story_text']}",
                provisional=score < 8.0,
            )
            store.add_case(case)
            imported += 1
    typer.echo(f"Imported {imported} case memory records into {memory_dir}")


if __name__ == "__main__":
    app()
