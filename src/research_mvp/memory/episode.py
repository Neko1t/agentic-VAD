from __future__ import annotations

from dataclasses import dataclass
import math

from ..artifacts.hashes import bytes_sha256
from ..contracts import MvpB2Output, MvpEpisode
from ..ids import episode_id
from ..math.numeric import (
    add,
    divide,
    multiply,
    numeric_equal,
    ordered_dot,
    ordered_sum,
    require_signed_unit,
    require_unit,
    square_root,
    subtract,
)


_STATES = {"NORMAL", "SUSPICIOUS", "ABNORMAL", "RECOVERING"}
EPS_CASE = 2.0**-52


@dataclass(frozen=True, slots=True)
class MvpEpisodeWindow:
    window_ordinal: int
    window_id: str
    delta_us: int
    final_b2: MvpB2Output


@dataclass(frozen=True, slots=True)
class MvpEpisodeSummary:
    reliability: float
    direction: float
    uncertainty: float
    consistency: float
    kappa_case_audit: float
    atom_ids: tuple[str, ...]
    embedding: tuple[float, ...] | None
    tokens: tuple[str, ...]
    temporal_triples: tuple[tuple[str, str, str], ...]
    medoid_window_id: str | None


def _valid_embedding(value: tuple[float, ...] | None) -> bool:
    return value is not None and bool(value) and all(math.isfinite(item) for item in value)


def _reference_medoid(windows: tuple[MvpEpisodeWindow, ...]) -> MvpEpisodeWindow | None:
    available = tuple(window for window in windows if _valid_embedding(window.final_b2.embedding))
    if not available:
        return None
    dimensions: dict[int, list[MvpEpisodeWindow]] = {}
    for window in available:
        dimensions.setdefault(len(window.final_b2.embedding or ()), []).append(window)
    selected_dimension = min(dimensions, key=lambda dimension: (-len(dimensions[dimension]), dimension))
    candidates = tuple(dimensions[selected_dimension])

    def objective(candidate: MvpEpisodeWindow) -> tuple[float, bytes]:
        vector = candidate.final_b2.embedding or ()
        distance = ordered_sum(
            subtract(1.0, ordered_dot(vector, other.final_b2.embedding or ()))
            for other in candidates
        )
        return distance, bytes.fromhex(bytes_sha256(candidate.window_id.encode("utf-8")))

    return min(candidates, key=objective)


def summarize_episode(
    episode: MvpEpisode,
    windows: tuple[MvpEpisodeWindow, ...],
) -> MvpEpisodeSummary:
    by_ordinal = {window.window_ordinal: window for window in windows}
    if len(by_ordinal) != len(windows):
        raise ValueError("Episode summary received duplicate window ordinals")
    try:
        ordered = tuple(by_ordinal[ordinal] for ordinal in episode.member_window_ordinals)
    except KeyError as exc:
        raise ValueError("Episode summary is missing a member window") from exc
    if not ordered:
        raise ValueError("Episode summary requires member windows")
    if any(
        isinstance(window.delta_us, bool)
        or not isinstance(window.delta_us, int)
        or window.delta_us <= 0
        or window.delta_us > 2**63 - 1
        for window in ordered
    ):
        raise ValueError("Episode delta_us must be positive int64")
    total_delta = ordered_sum(float(window.delta_us) for window in ordered)
    if total_delta <= 0.0:
        raise ValueError("Episode total duration must be positive")
    weights = tuple(divide(float(window.delta_us), total_delta) for window in ordered)
    reliabilities = tuple(
        multiply(window.final_b2.quality, subtract(1.0, window.final_b2.conflict))
        for window in ordered
    )
    evidence = tuple(window.final_b2.e_local for window in ordered)
    for reliability, value, window in zip(reliabilities, evidence, ordered, strict=True):
        if not numeric_equal(value, multiply(reliability, window.final_b2.direction)):
            raise ValueError("Episode input is not a local-final-B2 evidence tuple")
    q_case = require_unit(
        ordered_sum(multiply(weight, reliability) for weight, reliability in zip(weights, reliabilities, strict=True)),
        "Episode reliability",
    )
    numerator = ordered_sum(multiply(weight, value) for weight, value in zip(weights, evidence, strict=True))
    direction = require_signed_unit(divide(numerator, q_case) if q_case > 0.0 else 0.0, "Episode direction")
    uncertainty = require_unit(subtract(1.0, abs(numerator)), "Episode uncertainty")
    directional_mass = ordered_sum(
        multiply(weight, abs(value)) for weight, value in zip(weights, evidence, strict=True)
    )
    consistency = (
        require_unit(divide(abs(numerator), add(directional_mass, EPS_CASE)), "Episode consistency")
        if directional_mass > 0.0
        else 0.0
    )
    kappa_case = subtract(1.0, consistency) if directional_mass > 0.0 else 0.0
    atom_ids = tuple(
        sorted(
            {
                atom_id
                for window in ordered
                for atom_id in (*window.final_b2.supporting_atom_ids, *window.final_b2.counter_atom_ids)
            },
            key=lambda value: value.encode("utf-8"),
        )
    )

    medoid: MvpEpisodeWindow | None = None
    embedding: tuple[float, ...] | None = None
    if episode.role == "REFERENCE":
        core = tuple(by_ordinal[ordinal] for ordinal in episode.core_window_ordinals if ordinal in by_ordinal)
        medoid = _reference_medoid(core)
        tokens = () if medoid is None else medoid.final_b2.fact_tokens
        triples = () if medoid is None else medoid.final_b2.temporal_triples
        embedding = None if medoid is None else medoid.final_b2.embedding
    elif episode.role == "SALIENT":
        tokens = tuple(
            sorted({token for window in ordered for token in window.final_b2.fact_tokens}, key=lambda value: value.encode("utf-8"))
        )
        triples = tuple(sorted({triple for window in ordered for triple in window.final_b2.temporal_triples}))
        vector_windows = tuple((weight, window) for weight, window in zip(weights, ordered, strict=True) if _valid_embedding(window.final_b2.embedding))
        if vector_windows:
            dimensions = {len(window.final_b2.embedding or ()) for _, window in vector_windows}
            if len(dimensions) == 1:
                dimension = next(iter(dimensions))
                raw = tuple(
                    ordered_sum(
                        multiply(weight, (window.final_b2.embedding or ())[index])
                        for weight, window in vector_windows
                    )
                    for index in range(dimension)
                )
                norm = square_root(ordered_sum(multiply(value, value) for value in raw))
                embedding = tuple(divide(value, norm) for value in raw) if norm > 0.0 else None
    else:
        raise ValueError("Episode role is outside the frozen MVP set")

    return MvpEpisodeSummary(
        reliability=q_case,
        direction=direction,
        uncertainty=uncertainty,
        consistency=consistency,
        kappa_case_audit=require_unit(kappa_case, "Episode conflict audit"),
        atom_ids=atom_ids,
        embedding=embedding,
        tokens=tokens,
        temporal_triples=triples,
        medoid_window_id=None if medoid is None else medoid.window_id,
    )


@dataclass(slots=True)
class _OpenEpisode:
    role: str
    ordinal: int
    core: list[int]
    members: list[int]


class EpisodeBuilder:
    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.next_window_ordinal = 0
        self._previous_active: bool | None = None
        self._open: _OpenEpisode | None = None
        self._closed: list[MvpEpisode] = []
        self._role_ordinals = {"REFERENCE": 0, "SALIENT": 0}
        self._video_closed = False

    @property
    def closed_episodes(self) -> tuple[MvpEpisode, ...]:
        return tuple(self._closed)

    def _open_episode(self, role: str, core: list[int], members: list[int]) -> None:
        ordinal = self._role_ordinals[role]
        self._role_ordinals[role] += 1
        self._open = _OpenEpisode(role, ordinal, core, members)

    def _close_open(self) -> MvpEpisode:
        if self._open is None:
            raise ValueError("no open Episode")
        role_lower = self._open.role.casefold()
        episode = MvpEpisode(
            episode_id=episode_id(self.video_id, role_lower, self._open.ordinal),
            video_id=self.video_id,
            role=self._open.role,
            ordinal=self._open.ordinal,
            core_window_ordinals=tuple(self._open.core),
            member_window_ordinals=tuple(self._open.members),
            closed=True,
            visible_from_window_ordinal=max(self._open.members) + 1,
        )
        self._closed.append(episode)
        self._open = None
        return episode

    def feed(self, window_ordinal: int, state: str, *, artifact_accepted: bool) -> tuple[MvpEpisode, ...]:
        if self._video_closed:
            raise ValueError("video Episode builder is closed")
        if not artifact_accepted:
            raise ValueError("Episode update requires an accepted WindowArtifact")
        if window_ordinal != self.next_window_ordinal:
            raise ValueError("MVP window order violation")
        if state not in _STATES:
            raise ValueError("invalid B4 state")
        before_count = len(self._closed)
        active = state != "NORMAL"
        if self._previous_active is None:
            self._open_episode("SALIENT" if active else "REFERENCE", [window_ordinal], [window_ordinal])
        elif not self._previous_active and active:
            self._close_open()
            members = [window_ordinal - 1, window_ordinal] if window_ordinal > 0 else [window_ordinal]
            self._open_episode("SALIENT", [window_ordinal], members)
        elif self._previous_active and not active:
            if self._open is None:
                raise ValueError("Episode state is inconsistent")
            self._open.members.append(window_ordinal)
            self._close_open()
            self._open_episode("REFERENCE", [window_ordinal], [window_ordinal])
        else:
            if self._open is None:
                raise ValueError("Episode state is inconsistent")
            self._open.core.append(window_ordinal)
            if window_ordinal not in self._open.members:
                self._open.members.append(window_ordinal)
        self._previous_active = active
        self.next_window_ordinal += 1
        return tuple(self._closed[before_count:])

    def readable_sessions(self, query_video_id: str, query_window_ordinal: int) -> tuple[MvpEpisode, ...]:
        if self._video_closed or query_video_id != self.video_id:
            return ()
        return tuple(
            episode
            for episode in self._closed
            if episode.closed and episode.visible_from_window_ordinal <= query_window_ordinal
        )

    def close_video(self) -> tuple[MvpEpisode, ...]:
        if self._video_closed:
            raise ValueError("video already closed")
        if self._open is not None:
            self._close_open()
        self._video_closed = True
        return tuple(self._closed)
