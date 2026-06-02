from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import typer

from src.core.config import MemoryConfig
from src.core.schemas import PatternMemoryRecord
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.pattern_store import PatternMemoryStore

app = typer.Typer(add_completion=False, help="Extract simple pattern prototypes from accumulated case memory.")


@app.command()
def main(
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    min_support: int = typer.Option(2, min=1),
) -> None:
    config = MemoryConfig(storage_dir=memory_dir)
    case_store = CaseMemoryStore(
        storage_dir=config.storage_dir,
        collection_name=config.case_collection_name,
        provisional_collection_name=config.provisional_collection_name,
        embedding_builder=EmbeddingBuilder(model_name=config.embedding_model_name),
        use_chroma=False,
    )
    pattern_store = PatternMemoryStore(config.storage_dir / config.pattern_file_name)
    grouped: Dict[Tuple[str, str], List[object]] = defaultdict(list)
    for record in case_store.list_cases(provisional=False):
        grouped[(record.label, record.action_sequence)].append(record)

    patterns: List[PatternMemoryRecord] = []
    for (label, action_sequence), records in grouped.items():
        if len(records) < min_support:
            continue
        pattern_id = f"pattern_{abs(hash((label, action_sequence))) % 10_000_000}"
        average_risk = sum(record.risk_score for record in records) / len(records)
        scene_constraints = sorted({record.scene_type for record in records if record.scene_type})
        supporting_cases = [record.case_id for record in records]
        counter_examples = [record.case_id for record in case_store.list_cases(provisional=False) if record.action_sequence != action_sequence][:3]
        patterns.append(
            PatternMemoryRecord(
                pattern_id=pattern_id,
                pattern_name=f"{label}:{action_sequence}",
                prototype_action_sequence=action_sequence,
                scene_constraints=scene_constraints,
                risk_level=average_risk,
                supporting_cases=supporting_cases,
                counter_examples=counter_examples,
                rule_text=(
                    f"When action sequence '{action_sequence}' appears in scenes {', '.join(scene_constraints) or 'unknown'}, "
                    f"historical cases suggest average risk {average_risk:.2f}."
                ),
            )
        )
    pattern_store.add_patterns(patterns)
    typer.echo(f"Wrote {len(patterns)} pattern prototypes to {pattern_store.storage_file}")


if __name__ == "__main__":
    app()
