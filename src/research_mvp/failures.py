from __future__ import annotations

from dataclasses import dataclass


ATTEMPT_FATAL = "ATTEMPT_FATAL"
RECOVERABLE = "RECOVERABLE"


@dataclass
class MvpFailure(RuntimeError):
    """Safe failure value whose text never includes arbitrary payloads."""

    code: str
    severity: str
    safe_message: str

    def __str__(self) -> str:
        return f"{self.code}/{self.severity}: {self.safe_message}"


def fatal(code: str, safe_message: str) -> MvpFailure:
    return MvpFailure(code=code, severity=ATTEMPT_FATAL, safe_message=safe_message)


def recoverable(code: str, safe_message: str) -> MvpFailure:
    return MvpFailure(code=code, severity=RECOVERABLE, safe_message=safe_message)
