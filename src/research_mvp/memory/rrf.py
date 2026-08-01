from __future__ import annotations

from functools import cmp_to_key

from ..contracts import MvpRetrievalKey
from ..math.numeric import add, compare, divide


VIEW_ORDER = ("DENSE", "SPARSE_BM25", "TEMPORAL")
RRF_CONSTANT = 60


def rrf_order(
    available_views: tuple[tuple[str, tuple[tuple[str, float], ...]], ...],
    cases_by_id: dict[str, MvpRetrievalKey],
    limit: int,
) -> tuple[tuple[str, float], ...]:
    scores: dict[str, float] = {}
    for expected_name in VIEW_ORDER:
        matching = tuple(hits for name, hits in available_views if name == expected_name)
        if not matching:
            continue
        for rank, (case_id, _score) in enumerate(matching[0], start=1):
            scores[case_id] = add(scores.get(case_id, 0.0), divide(1.0, float(RRF_CONSTANT + rank)))

    def compare_ids(left: str, right: str) -> int:
        numeric = compare(scores[left], scores[right])
        if numeric:
            return -numeric
        left_case = cases_by_id[left]
        right_case = cases_by_id[right]
        left_tie = (bytes.fromhex(left_case.key_hash), left.encode("utf-8"))
        right_tie = (bytes.fromhex(right_case.key_hash), right.encode("utf-8"))
        return -1 if left_tie < right_tie else (1 if left_tie > right_tie else 0)

    ordered = sorted(scores, key=cmp_to_key(compare_ids))
    return tuple((case_id, scores[case_id]) for case_id in ordered[:limit])
