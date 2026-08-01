from __future__ import annotations

import math

import pytest

from src.research_mvp.codec import MvpCodecError, dumps, loads, payload_hash
from src.research_mvp.ids import case_id, episode_id, validate_attempt_id, window_semantic_id


def test_mvp_json_v0_is_stable_utf8_and_normalizes_negative_zero() -> None:
    payload = {"汉字": "值", "b": -0.0, "a": [1, 2.5]}

    encoded = dumps(payload)

    assert encoded == '{"a":[1,2.5],"b":0.0,"汉字":"值"}'.encode()
    assert loads(encoded) == {"a": [1, 2.5], "b": 0.0, "汉字": "值"}
    assert payload_hash(payload) == payload_hash(loads(encoded))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":9223372036854775808}',
        b'{"x":-9223372036854775809}',
        b'"\\ud800"',
    ],
)
def test_mvp_json_v0_rejects_non_domain_values(raw: bytes) -> None:
    with pytest.raises(MvpCodecError):
        loads(raw)


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, 2**63, -(2**63) - 1, "\udfff"],
)
def test_encoder_rejects_non_domain_values(value: object) -> None:
    with pytest.raises(MvpCodecError):
        dumps({"value": value})


def test_stable_ids_exclude_attempt_and_are_semantic() -> None:
    assert validate_attempt_id("mvp-synth-a") == "mvp-synth-a"
    assert episode_id("mvp-video-b-salient", "salient", 0) == "mvp-episode-b-salient-0000"
    assert case_id("mvp-video-b-salient", "salient", 0) == "mvp-case-b-salient-0000"
    assert window_semantic_id("mvp-video-c-query", 2) == "mvp-video-c-query-window-0002"
    with pytest.raises(ValueError):
        validate_attempt_id("../latest")
