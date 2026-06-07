from __future__ import annotations

from typing import Dict, Tuple

from src.core.schemas import CaseMemoryRecord, RetrievedCase, RetrievalQuery, RetrievalResult
from src.memory.case_store import CaseMemoryStore
from src.memory.pattern_store import PatternMemoryStore
from src.memory.session_store import SessionMemoryStore


class RAGTool:
    def __init__(
        self,
        case_store: CaseMemoryStore,
        pattern_store: PatternMemoryStore,
        session_store: SessionMemoryStore | None = None,
    ):
        self.case_store = case_store
        self.pattern_store = pattern_store
        self.session_store = session_store

    def rag_store(self, case_record: CaseMemoryRecord) -> str:
        return self.case_store.add_case(case_record)

    def rag_store_session(self, case_record: CaseMemoryRecord) -> str:
        if self.session_store is None:
            return case_record.case_id
        return self.session_store.add_case(case_record)

    def rag_retrieve(self, query_struct: RetrievalQuery, top_k: int = 5) -> RetrievalResult:
        base_result = self.case_store.retrieve(query_struct, top_k=top_k)
        if self.session_store is not None:
            session_result = self.session_store.retrieve(query_struct, top_k=top_k)
            base_result = self._merge_results(base_result, session_result, top_k=top_k)
        matched_patterns = self.pattern_store.retrieve(query_struct.action_sequence, top_k=min(3, top_k))
        return base_result.model_copy(update={"matched_patterns": matched_patterns})

    def _merge_results(
        self,
        base_result: RetrievalResult,
        session_result: RetrievalResult,
        top_k: int,
    ) -> RetrievalResult:
        cases: Dict[str, Tuple[float, RetrievedCase]] = {}
        for case in base_result.similar_cases:
            cases[case.case_id] = (case.score, case)
        for case in session_result.similar_cases:
            existing = cases.get(case.case_id)
            if existing is None or case.score > existing[0]:
                cases[case.case_id] = (case.score, case)
        merged = sorted(cases.values(), key=lambda item: item[0], reverse=True)[:top_k]
        return RetrievalResult(
            similar_cases=[case for _, case in merged],
            matched_patterns=base_result.matched_patterns,
            retrieval_confidence=max(base_result.retrieval_confidence, session_result.retrieval_confidence),
        )
