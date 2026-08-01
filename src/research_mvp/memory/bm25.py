from __future__ import annotations

from collections import Counter
from functools import cmp_to_key

from ..contracts import MvpRetrievalKey
from ..math.numeric import add, compare, divide, logarithm, multiply, ordered_sum


K1 = 1.2
B = 0.75


def _compare_hits(left: tuple[MvpRetrievalKey, float], right: tuple[MvpRetrievalKey, float]) -> int:
    numeric = compare(left[1], right[1])
    if numeric:
        return -numeric
    left_tie = (bytes.fromhex(left[0].key_hash), left[0].case_id.encode("utf-8"))
    right_tie = (bytes.fromhex(right[0].key_hash), right[0].case_id.encode("utf-8"))
    return -1 if left_tie < right_tie else (1 if left_tie > right_tie else 0)


def bm25_view(
    query_tokens: tuple[str, ...],
    cases: tuple[MvpRetrievalKey, ...],
    limit: int,
) -> tuple[tuple[str, float], ...] | None:
    normalized_query = tuple(sorted(set(token.casefold() for token in query_tokens), key=lambda value: value.encode("utf-8")))
    if not normalized_query or not cases:
        return None
    ordered_cases = tuple(sorted(cases, key=lambda item: (bytes.fromhex(item.key_hash), item.case_id.encode("utf-8"))))
    lengths = tuple(len(case.tokens) for case in ordered_cases)
    average_length = divide(ordered_sum(float(value) for value in lengths), float(len(ordered_cases)))
    if average_length == 0.0:
        return None
    document_frequency = {
        term: sum(1 for case in ordered_cases if term in set(token.casefold() for token in case.tokens))
        for term in normalized_query
    }
    hits: list[tuple[MvpRetrievalKey, float]] = []
    count = float(len(ordered_cases))
    for case in ordered_cases:
        frequencies = Counter(token.casefold() for token in case.tokens)
        parts: list[float] = []
        for term in normalized_query:
            frequency = float(frequencies[term])
            df = float(document_frequency[term])
            idf = logarithm(add(1.0, divide(add(add(count, -df), 0.5), add(df, 0.5))))
            length_ratio = divide(float(len(case.tokens)), average_length)
            normalization = add(subtract_one_minus_b(), multiply(B, length_ratio))
            denominator = add(frequency, multiply(K1, normalization))
            numerator = multiply(frequency, add(K1, 1.0))
            part = 0.0 if denominator == 0.0 else multiply(idf, divide(numerator, denominator))
            parts.append(part)
        hits.append((case, ordered_sum(parts)))
    hits.sort(key=cmp_to_key(_compare_hits))
    return tuple((case.case_id, score) for case, score in hits[:limit])


def subtract_one_minus_b() -> float:
    return 1.0 - B
