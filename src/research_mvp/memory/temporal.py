from __future__ import annotations

from functools import cmp_to_key

from ..contracts import MvpObservedTemporalFact, MvpRetrievalKey
from ..math.numeric import compare, divide


_INVERSE = {
    "before": "after",
    "after": "before",
    "meets": "met_by",
    "met_by": "meets",
    "overlaps": "overlapped_by",
    "overlapped_by": "overlaps",
    "starts": "started_by",
    "started_by": "starts",
    "during": "contains",
    "contains": "during",
    "finishes": "finished_by",
    "finished_by": "finishes",
    "equal": "equal",
}


def _allen_relation(left: MvpObservedTemporalFact, right: MvpObservedTemporalFact) -> str:
    a = left.interval
    b = right.interval
    if a.end_us < b.start_us:
        return "before"
    if a.end_us == b.start_us:
        return "meets"
    if a.start_us == b.start_us and a.end_us == b.end_us:
        return "equal"
    if a.start_us == b.start_us and a.end_us < b.end_us:
        return "starts"
    if b.start_us < a.start_us and a.end_us < b.end_us:
        return "during"
    if b.start_us < a.start_us and a.end_us == b.end_us:
        return "finishes"
    if a.start_us < b.start_us < a.end_us < b.end_us:
        return "overlaps"
    return _INVERSE[_allen_relation(right, left)]


def derive_allen_triples(
    facts: tuple[MvpObservedTemporalFact, ...],
) -> tuple[tuple[str, str, str], ...]:
    by_id: dict[str, MvpObservedTemporalFact] = {}
    for fact in facts:
        if not fact.fact_id:
            raise ValueError("observed temporal fact ID must be non-empty")
        previous = by_id.get(fact.fact_id)
        if previous is not None and previous != fact:
            raise ValueError("observed temporal fact ID has conflicting intervals")
        by_id[fact.fact_id] = fact
    ordered = tuple(by_id[key] for key in sorted(by_id, key=lambda value: value.encode("utf-8")))
    triples: set[tuple[str, str, str]] = set()
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            relation = _allen_relation(left, right)
            triples.add((left.fact_id, relation, right.fact_id))
            triples.add((right.fact_id, _INVERSE[relation], left.fact_id))
    return tuple(sorted(triples, key=lambda item: tuple(part.encode("utf-8") for part in item)))


def _compare_hits(left: tuple[MvpRetrievalKey, float], right: tuple[MvpRetrievalKey, float]) -> int:
    numeric = compare(left[1], right[1])
    if numeric:
        return -numeric
    left_tie = (bytes.fromhex(left[0].key_hash), left[0].case_id.encode("utf-8"))
    right_tie = (bytes.fromhex(right[0].key_hash), right[0].case_id.encode("utf-8"))
    return -1 if left_tie < right_tie else (1 if left_tie > right_tie else 0)


def temporal_view(
    query_triples: tuple[tuple[str, str, str], ...],
    cases: tuple[MvpRetrievalKey, ...],
    limit: int,
) -> tuple[tuple[str, float], ...] | None:
    query = set(query_triples)
    if not query:
        return None
    hits = [
        (case, divide(float(len(query.intersection(case.temporal_triples))), float(len(query))))
        for case in sorted(cases, key=lambda item: (bytes.fromhex(item.key_hash), item.case_id.encode("utf-8")))
    ]
    hits.sort(key=cmp_to_key(_compare_hits))
    return tuple((case.case_id, score) for case, score in hits[:limit])
