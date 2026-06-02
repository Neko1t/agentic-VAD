from __future__ import annotations

from src.core.schemas import CaseMemoryRecord, RetrievalQuery, RetrievalResult
from src.memory.case_store import CaseMemoryStore
from src.memory.pattern_store import PatternMemoryStore


class RAGTool:
    def __init__(self, case_store: CaseMemoryStore, pattern_store: PatternMemoryStore):
        self.case_store = case_store
        self.pattern_store = pattern_store

    def rag_store(self, case_record: CaseMemoryRecord) -> str:
        return self.case_store.add_case(case_record)

    def rag_retrieve(self, query_struct: RetrievalQuery, top_k: int = 5) -> RetrievalResult:
        base_result = self.case_store.retrieve(query_struct, top_k=top_k)
        matched_patterns = self.pattern_store.retrieve(query_struct.action_sequence, top_k=min(3, top_k))
        return base_result.model_copy(update={"matched_patterns": matched_patterns})
