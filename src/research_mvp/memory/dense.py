from __future__ import annotations

from functools import cmp_to_key

from ..contracts import MvpRetrievalKey
from ..math.numeric import compare, ordered_dot


def _compare_hits(left: tuple[MvpRetrievalKey, float], right: tuple[MvpRetrievalKey, float]) -> int:
    numeric = compare(left[1], right[1])
    if numeric:
        return -numeric
    left_tie = (bytes.fromhex(left[0].key_hash), left[0].case_id.encode("utf-8"))
    right_tie = (bytes.fromhex(right[0].key_hash), right[0].case_id.encode("utf-8"))
    return -1 if left_tie < right_tie else (1 if left_tie > right_tie else 0)


def dense_view(
    query_embedding: tuple[float, ...] | None,
    cases: tuple[MvpRetrievalKey, ...],
    limit: int,
) -> tuple[tuple[str, float], ...] | None:
    if query_embedding is None:
        return None
    hits: list[tuple[MvpRetrievalKey, float]] = []
    for case in sorted(cases, key=lambda item: (bytes.fromhex(item.key_hash), item.case_id.encode("utf-8"))):
        if case.embedding is None:
            continue
        hits.append((case, ordered_dot(query_embedding, case.embedding)))
    hits.sort(key=cmp_to_key(_compare_hits))
    return tuple((case.case_id, score) for case, score in hits[:limit])
