from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class MvpCodecError(ValueError):
    pass


def _valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < INT64_MIN or value > INT64_MAX:
            raise MvpCodecError("integer is outside signed int64")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MvpCodecError("non-finite float is forbidden")
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        if not _valid_unicode(value):
            raise MvpCodecError("lone surrogate is forbidden")
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _valid_unicode(key):
                raise MvpCodecError("object keys must be valid Unicode strings")
            normalized[key] = _normalize(item)
        return normalized
    raise MvpCodecError(f"unsupported MVP JSON type: {type(value).__name__}")


def dumps(value: Any) -> bytes:
    normalized = _normalize(value)
    try:
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return text.encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise MvpCodecError("value is not encodable by MVP_JSON_V0") from exc


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MvpCodecError("duplicate object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise MvpCodecError("non-finite JSON number is forbidden")


def loads(raw: bytes | str) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        if text.startswith("\ufeff"):
            raise MvpCodecError("BOM is forbidden")
        parsed = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except MvpCodecError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MvpCodecError("invalid MVP_JSON_V0 input") from exc
    return _normalize(parsed)


def payload_hash(value: Any) -> str:
    return hashlib.sha256(dumps(value)).hexdigest()
