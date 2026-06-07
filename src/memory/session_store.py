from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from src.core.schemas import CaseMemoryRecord, RetrievedCase, RetrievalQuery, RetrievalResult
from src.memory.embedding_builder import EmbeddingBuilder


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


class SessionMemoryStore:
    """In-memory per-run memory for current-video retrieval."""

    def __init__(self, embedding_builder: EmbeddingBuilder):
        self.embedding_builder = embedding_builder
        self._records: Dict[str, CaseMemoryRecord] = {}
        self._vectors: Dict[str, List[float]] = {}

    def add_case(self, record: CaseMemoryRecord) -> str:
        self._records[record.case_id] = record
        self._vectors[record.case_id] = self.embedding_builder.embed_texts([record.embedding_text])[0]
        return record.case_id

    def clear_video(self, video_id: str) -> None:
        case_ids = [case_id for case_id, record in self._records.items() if record.video_id == video_id]
        for case_id in case_ids:
            self._records.pop(case_id, None)
            self._vectors.pop(case_id, None)

    def list_cases(self, video_id: str | None = None) -> List[CaseMemoryRecord]:
        records = list(self._records.values())
        if video_id is None:
            return records
        return [record for record in records if record.video_id == video_id]

    def retrieve(self, query: RetrievalQuery, top_k: int = 5) -> RetrievalResult:
        query_text = self._format_query_text(query)
        if not query_text.strip():
            return RetrievalResult()
        query_vector = self.embedding_builder.embed_texts([query_text])[0]
        scored: List[Tuple[float, RetrievedCase]] = []
        for record in self.list_cases(video_id=query.video_id):
            vector = self._vectors.get(record.case_id)
            if vector is None:
                continue
            similarity = _cosine_similarity(query_vector, vector)
            if similarity <= 0.0:
                continue
            scored.append(
                (
                    similarity,
                    RetrievedCase(
                        case_id=record.case_id,
                        video_id=record.video_id,
                        score=similarity,
                        episode_summary=record.episode_summary,
                        action_sequence=record.action_sequence,
                        risk_score=record.risk_score,
                        evidence_tags=record.evidence_tags,
                        metadata={
                            "scene_type": record.scene_type,
                            "source": "session_memory",
                            "provisional": record.provisional,
                            "case_type": record.case_type.value,
                        },
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        merged = scored[:top_k]
        top_score = merged[0][0] if merged else 0.0
        return RetrievalResult(
            similar_cases=[record for _, record in merged],
            matched_patterns=[],
            retrieval_confidence=max(0.0, min(1.0, top_score)),
        )

    def _format_query_text(self, query: RetrievalQuery) -> str:
        parts = [query.action_sequence]
        if query.scene_type:
            parts.append(query.scene_type)
        if query.evidence_tags:
            parts.append(" ".join(query.evidence_tags))
        if query.story_text:
            parts.append(query.story_text)
        return " | ".join(part for part in parts if part)
