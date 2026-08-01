from __future__ import annotations

from collections.abc import Iterable

from ..codec import payload_hash
from ..contracts import MvpRetrievalKey


_FORBIDDEN = ("state", "score", "reliability", "consistency", "novelty", "advisory", "label", "annotation")


def build_retrieval_key(
    *,
    case_id: str,
    source_video_id: str,
    scope: str,
    payload_hash_value: str,
    embedding: Iterable[float] | None,
    tokens: Iterable[str],
    temporal_triples: Iterable[tuple[str, str, str]],
    visible_from_window_ordinal: int | None = None,
) -> MvpRetrievalKey:
    normalized_tokens = tuple(sorted(set(str(token).casefold() for token in tokens), key=lambda value: value.encode("utf-8")))
    normalized_triples = tuple(sorted(set(tuple(str(part) for part in triple) for triple in temporal_triples)))
    key_payload = {
        "embedding": None if embedding is None else [float(value) for value in embedding],
        "scope": scope,
        "source_video_id": source_video_id,
        "temporal_triples": [list(item) for item in normalized_triples],
        "tokens": list(normalized_tokens),
        "visible_from_window_ordinal": visible_from_window_ordinal,
    }
    keys_text = " ".join(key_payload).casefold()
    if any(term in keys_text for term in _FORBIDDEN):
        raise ValueError("RetrievalKey contains a forbidden field")
    return MvpRetrievalKey(
        case_id=case_id,
        source_video_id=source_video_id,
        scope=scope,
        key_hash=payload_hash(key_payload),
        payload_hash=payload_hash_value,
        embedding=None if embedding is None else tuple(float(value) for value in embedding),
        tokens=normalized_tokens,
        temporal_triples=normalized_triples,
        visible_from_window_ordinal=visible_from_window_ordinal,
    )
