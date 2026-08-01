from __future__ import annotations

import math
import struct
from collections.abc import Iterable


ABS_TOL = 1e-12
REL_TOL = 1e-9


def binary64(value: float | int) -> float:
    return struct.unpack(">d", struct.pack(">d", float(value)))[0]


def add(left: float, right: float) -> float:
    return binary64(binary64(left) + binary64(right))


def subtract(left: float, right: float) -> float:
    return binary64(binary64(left) - binary64(right))


def multiply(left: float, right: float) -> float:
    return binary64(binary64(left) * binary64(right))


def divide(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        raise ZeroDivisionError("ordered binary64 division by zero")
    return binary64(binary64(numerator) / binary64(denominator))


def exp(value: float) -> float:
    return binary64(math.exp(binary64(value)))


def logarithm(value: float) -> float:
    return binary64(math.log(binary64(value)))


def square_root(value: float) -> float:
    return binary64(math.sqrt(binary64(value)))


def ordered_sum(values: Iterable[float]) -> float:
    accumulator = binary64(0.0)
    for value in values:
        accumulator = add(accumulator, binary64(value))
    return accumulator


def ordered_product(values: Iterable[float]) -> float:
    accumulator = binary64(1.0)
    for value in values:
        accumulator = multiply(accumulator, binary64(value))
    return accumulator


def ordered_dot(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = tuple(left)
    right_values = tuple(right)
    if len(left_values) != len(right_values):
        raise ValueError("ordered dot dimensions differ")
    accumulator = binary64(0.0)
    for lhs, rhs in zip(left_values, right_values, strict=True):
        accumulator = add(accumulator, multiply(lhs, rhs))
    return accumulator


def tolerance(left: float, right: float) -> float:
    return max(ABS_TOL, REL_TOL * max(abs(left), abs(right)))


def compare(left: float, right: float) -> int:
    if left - right > tolerance(left, right):
        return 1
    if right - left > tolerance(left, right):
        return -1
    return 0


def numeric_equal(left: float, right: float) -> bool:
    return compare(left, right) == 0


def strict_greater(left: float, right: float) -> bool:
    return compare(left, right) == 1


def require_unit(value: float, name: str = "value") -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < -tolerance(value, 0.0) or value > 1.0 + tolerance(value, 1.0):
        raise ValueError(f"{name} must be in [0,1]")
    return binary64(min(1.0, max(0.0, value)))


def require_signed_unit(value: float, name: str = "value") -> float:
    if not math.isfinite(value) or value < -1.0 - tolerance(value, -1.0) or value > 1.0 + tolerance(value, 1.0):
        raise ValueError(f"{name} must be in [-1,1]")
    return binary64(min(1.0, max(-1.0, value)))


def median(values: Iterable[float]) -> float:
    ordered = sorted(binary64(value) for value in values)
    if not ordered:
        raise ValueError("median requires values")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return divide(add(ordered[middle - 1], ordered[middle]), 2.0)
