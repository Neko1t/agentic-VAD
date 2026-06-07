from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import typer

from src.core.config import MemoryConfig
from src.memory.case_store import CaseMemoryStore
from src.memory.embedding_builder import EmbeddingBuilder
from src.memory.promotion import MemoryPromotionPolicy

app = typer.Typer(add_completion=False, help="Promote provisional case memory records after offline review gates.")


def promote_cases(
    memory_dir: Path,
    case_ids: List[str] | None = None,
    dry_run: bool = False,
    high_risk_threshold: float = 8.0,
    hard_negative_threshold: float = 2.5,
    max_uncertainty: float = 0.35,
    min_evidence_tags: int = 1,
) -> Dict[str, object]:
    config = MemoryConfig(storage_dir=memory_dir)
    store = CaseMemoryStore(
        storage_dir=config.storage_dir,
        collection_name=config.case_collection_name,
        provisional_collection_name=config.provisional_collection_name,
        embedding_builder=EmbeddingBuilder(model_name=config.embedding_model_name),
        use_chroma=config.use_chroma,
    )
    policy = MemoryPromotionPolicy(
        high_risk_threshold=high_risk_threshold,
        hard_negative_threshold=hard_negative_threshold,
        max_uncertainty=max_uncertainty,
        min_evidence_tags=min_evidence_tags,
    )
    requested = set(case_ids or [])
    candidates = store.list_cases(provisional=True)
    if requested:
        candidates = [record for record in candidates if record.case_id in requested]

    promoted: List[str] = []
    skipped: List[Dict[str, object]] = []
    for record in candidates:
        decision = policy.decide(record)
        if decision.should_promote:
            if not dry_run:
                store.promote_case(record.case_id)
            promoted.append(record.case_id)
        else:
            skipped.append(
                {
                    "case_id": record.case_id,
                    "reason": decision.reason,
                    "skip_codes": decision.skip_codes,
                }
            )

    missing = sorted(requested - {record.case_id for record in candidates})
    return {
        "dry_run": dry_run,
        "promoted": promoted,
        "skipped": skipped,
        "missing": missing,
        "counts": {
            "promoted": len(promoted),
            "skipped": len(skipped),
            "missing": len(missing),
        },
    }


@app.command()
def main(
    memory_dir: Path = typer.Option(Path("./data/agentic_memory")),
    case_id: Optional[List[str]] = typer.Option(None, "--case-id"),
    dry_run: bool = typer.Option(False),
    high_risk_threshold: float = typer.Option(8.0, min=0.0, max=10.0),
    hard_negative_threshold: float = typer.Option(2.5, min=0.0, max=10.0),
    max_uncertainty: float = typer.Option(0.35, min=0.0, max=1.0),
    min_evidence_tags: int = typer.Option(1, min=0),
    report_path: Path | None = typer.Option(None),
) -> None:
    report = promote_cases(
        memory_dir=memory_dir,
        case_ids=case_id,
        dry_run=dry_run,
        high_risk_threshold=high_risk_threshold,
        hard_negative_threshold=hard_negative_threshold,
        max_uncertainty=max_uncertainty,
        min_evidence_tags=min_evidence_tags,
    )
    rendered = json.dumps(report, indent=2)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    typer.echo(rendered)


if __name__ == "__main__":
    app()
