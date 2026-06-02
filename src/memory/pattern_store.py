from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from src.core.schemas import PatternMemoryRecord


class PatternMemoryStore:
    def __init__(self, storage_file: Path):
        self.storage_file = storage_file
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> List[PatternMemoryRecord]:
        if not self.storage_file.exists():
            return []
        records: List[PatternMemoryRecord] = []
        with self.storage_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(PatternMemoryRecord.model_validate_json(line))
        return records

    def write_all(self, records: Iterable[PatternMemoryRecord]) -> None:
        with self.storage_file.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")

    def add_patterns(self, records: Iterable[PatternMemoryRecord]) -> None:
        existing = {record.pattern_id: record for record in self.load_all()}
        for record in records:
            existing[record.pattern_id] = record
        self.write_all(existing.values())

    def retrieve(self, action_sequence: str, top_k: int = 3) -> List[PatternMemoryRecord]:
        if not action_sequence:
            return []
        terms = set(action_sequence.lower().split("->"))
        scored = []
        for record in self.load_all():
            record_terms = set(record.prototype_action_sequence.lower().split("->"))
            overlap = len({term.strip() for term in terms if term.strip()} & {term.strip() for term in record_terms if term.strip()})
            if overlap:
                scored.append((overlap, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:top_k]]
