from __future__ import annotations

import re


_SAFE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")


def validate_attempt_id(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError("attempt_id must be a lowercase, path-free stable identifier")
    return value


def _video_suffix(video_id: str) -> str:
    prefix = "mvp-video-"
    if not video_id.startswith(prefix) or not _SAFE_ID.fullmatch(video_id):
        raise ValueError("invalid MVP video_id")
    return video_id[len(prefix) :]


def _role(value: str) -> str:
    normalized = value.casefold()
    if normalized not in {"reference", "salient"}:
        raise ValueError("episode role must be reference or salient")
    return normalized


def _episode_stem(video_id: str, role: str) -> str:
    suffix = _video_suffix(video_id)
    normalized_role = _role(role)
    if suffix == normalized_role or suffix.endswith(f"-{normalized_role}"):
        return suffix
    return f"{suffix}-{normalized_role}"


def episode_id(video_id: str, role: str, ordinal: int) -> str:
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("episode ordinal must be a non-negative integer")
    return f"mvp-episode-{_episode_stem(video_id, role)}-{ordinal:04d}"


def case_id(video_id: str, role: str, ordinal: int) -> str:
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("case ordinal must be a non-negative integer")
    return f"mvp-case-{_episode_stem(video_id, role)}-{ordinal:04d}"


def window_semantic_id(video_id: str, ordinal: int) -> str:
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("window ordinal must be a non-negative integer")
    _video_suffix(video_id)
    return f"{video_id}-window-{ordinal:04d}"
