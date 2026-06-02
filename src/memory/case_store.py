from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.core.schemas import CaseMemoryRecord, RetrievedCase, RetrievalQuery, RetrievalResult
from src.memory.embedding_builder import EmbeddingBuilder


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


class CaseMemoryStore:
    def __init__(
        self,
        storage_dir: Path,
        collection_name: str,
        provisional_collection_name: str,
        embedding_builder: EmbeddingBuilder,
        use_chroma: bool = True,
    ):
        self.storage_dir = storage_dir
        self.collection_name = collection_name
        self.provisional_collection_name = provisional_collection_name
        self.embedding_builder = embedding_builder
        self.use_chroma = use_chroma
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.records_file = self.storage_dir / "case_memory.jsonl"
        self._client = None
        self._collection = None
        self._provisional_collection = None
        self._chroma_error = None

    def _get_chroma_collection(self, provisional: bool = False):
        if not self.use_chroma:
            return None
        if provisional and self._provisional_collection is not None:
            return self._provisional_collection
        if not provisional and self._collection is not None:
            return self._collection
        try:
            import chromadb

            if self._client is None:
                self._client = chromadb.PersistentClient(path=str(self.storage_dir / "chroma"))
            name = self.provisional_collection_name if provisional else self.collection_name
            collection = self._client.get_or_create_collection(name=name)
            if provisional:
                self._provisional_collection = collection
            else:
                self._collection = collection
            return collection
        except Exception as exc:  # pragma: no cover - optional dependency path
            self._chroma_error = exc
            self.use_chroma = False
            return None

    def _load_records(self) -> List[CaseMemoryRecord]:
        if not self.records_file.exists():
            return []
        records: List[CaseMemoryRecord] = []
        with self.records_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(CaseMemoryRecord.model_validate_json(line))
        return records

    def _write_records(self, records: Iterable[CaseMemoryRecord]) -> None:
        with self.records_file.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")

    def add_case(self, record: CaseMemoryRecord) -> str:
        records = {existing.case_id: existing for existing in self._load_records()}
        records[record.case_id] = record
        self._write_records(records.values())
        self._index_record(record)
        return record.case_id

    def promote_case(self, case_id: str) -> bool:
        records = self._load_records()
        promoted = False
        updated: List[CaseMemoryRecord] = []
        for record in records:
            if record.case_id == case_id and record.provisional:
                record = record.model_copy(update={"provisional": False})
                promoted = True
            updated.append(record)
        if promoted:
            self._write_records(updated)
            self._rebuild_indexes(updated)
        return promoted

    def list_cases(self, provisional: Optional[bool] = None) -> List[CaseMemoryRecord]:
        records = self._load_records()
        if provisional is None:
            return records
        return [record for record in records if record.provisional == provisional]

    def _record_metadata(self, record: CaseMemoryRecord) -> Dict[str, object]:
        return {
            "case_id": record.case_id,
            "video_id": record.video_id,
            "risk_score": float(record.risk_score),
            "action_sequence": record.action_sequence,
            "scene_type": record.scene_type,
            "evidence_tags": json.dumps(record.evidence_tags),
            "episode_summary": record.episode_summary,
            "provisional": record.provisional,
        }

    def _index_record(self, record: CaseMemoryRecord) -> None:
        collection = self._get_chroma_collection(provisional=record.provisional)
        if collection is None:
            return
        embedding = self.embedding_builder.embed_texts([record.embedding_text])[0]
        metadata = self._record_metadata(record)
        collection.upsert(
            ids=[record.case_id],
            embeddings=[embedding],
            documents=[record.embedding_text],
            metadatas=[metadata],
        )

    def _rebuild_indexes(self, records: Iterable[CaseMemoryRecord]) -> None:
        if not self.use_chroma:
            return
        finalized = self._get_chroma_collection(provisional=False)
        provisional = self._get_chroma_collection(provisional=True)
        if finalized is not None:
            try:
                existing = finalized.get()
                if existing["ids"]:
                    finalized.delete(ids=existing["ids"])
            except Exception:
                pass
        if provisional is not None:
            try:
                existing = provisional.get()
                if existing["ids"]:
                    provisional.delete(ids=existing["ids"])
            except Exception:
                pass
        for record in records:
            self._index_record(record)

    def _format_query_text(self, query: RetrievalQuery) -> str:
        parts = [query.action_sequence]
        if query.scene_type:
            parts.append(query.scene_type)
        if query.evidence_tags:
            parts.append(" ".join(query.evidence_tags))
        if query.story_text:
            parts.append(query.story_text)
        return " | ".join(part for part in parts if part)

    def _retrieve_with_chroma(self, query: RetrievalQuery, top_k: int) -> List[Tuple[float, RetrievedCase]]:
        collection = self._get_chroma_collection(provisional=False)
        if collection is None:
            return []
        query_text = self._format_query_text(query)
        if not query_text.strip():
            return []
        embedding = self.embedding_builder.embed_texts([query_text])[0]
        results = collection.query(query_embeddings=[embedding], n_results=top_k)
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        retrieved: List[Tuple[float, RetrievedCase]] = []
        for case_id, distance, metadata in zip(ids, distances, metadatas):
            similarity = max(0.0, 1.0 - float(distance))
            record = RetrievedCase(
                case_id=case_id,
                video_id=str(metadata.get("video_id", "")),
                score=similarity,
                episode_summary=str(metadata.get("episode_summary", "")),
                action_sequence=str(metadata.get("action_sequence", "")),
                risk_score=float(metadata.get("risk_score", 0.0)),
                evidence_tags=json.loads(metadata.get("evidence_tags", "[]")),
                metadata=dict(metadata),
            )
            retrieved.append((similarity, record))
        return retrieved

    def _retrieve_fallback(self, query: RetrievalQuery, top_k: int) -> List[Tuple[float, RetrievedCase]]:
        query_text = self._format_query_text(query)
        if not query_text.strip():
            return []
        query_vector = self.embedding_builder.embed_texts([query_text])[0]
        scored: List[Tuple[float, RetrievedCase]] = []
        for record in self.list_cases(provisional=False):
            vector = self.embedding_builder.embed_texts([record.embedding_text])[0]
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
                        metadata={"scene_type": record.scene_type},
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:top_k]

    def retrieve(self, query: RetrievalQuery, top_k: int = 5) -> RetrievalResult:
        primary_query = query.model_copy(update={"story_text": ""})
        story_query = query
        primary = self._retrieve_with_chroma(primary_query, top_k) if self.use_chroma else []
        if not primary:
            primary = self._retrieve_fallback(primary_query, top_k)
        secondary = self._retrieve_with_chroma(story_query, top_k) if self.use_chroma else []
        if not secondary:
            secondary = self._retrieve_fallback(story_query, top_k)

        reranked: Dict[str, Tuple[float, RetrievedCase]] = {}
        for rank, (score, record) in enumerate(primary, start=1):
            reranked[record.case_id] = (score + 1.0 / rank, record)
        for rank, (score, record) in enumerate(secondary, start=1):
            existing = reranked.get(record.case_id)
            blended = score + 0.5 / rank
            if existing is None or blended > existing[0]:
                reranked[record.case_id] = (blended, record)
        merged = sorted(reranked.values(), key=lambda item: item[0], reverse=True)[:top_k]
        similar_cases = [record for _, record in merged]
        top_score = merged[0][0] if merged else 0.0
        retrieval_confidence = max(0.0, min(1.0, top_score / 2.0))
        return RetrievalResult(
            similar_cases=similar_cases,
            matched_patterns=[],
            retrieval_confidence=retrieval_confidence,
        )
