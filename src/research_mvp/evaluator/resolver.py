from __future__ import annotations

from pathlib import Path

from ..artifacts.hashes import file_sha256
from ..artifacts.resolver import resolve_relative
from ..failures import fatal


class MvpEvaluatorResolver:
    def __init__(self, root: Path, allowed: tuple[tuple[str, int, str], ...]) -> None:
        self.root = root
        self._allowed = {relative: (length, digest) for relative, length, digest in allowed}
        if len(self._allowed) != len(allowed):
            raise fatal("MVP_PATH_ESCAPE", "Evaluator input allowlist contains aliases")
        for relative in self._allowed:
            resolve_relative(root, relative)

    def read(self, relative: str) -> bytes:
        if relative not in self._allowed:
            raise fatal("MVP_PATH_ESCAPE", "Evaluator resolver denied an unregistered input")
        expected_length, expected_hash = self._allowed[relative]
        path = resolve_relative(self.root, relative)
        try:
            if path.stat().st_size != expected_length or file_sha256(path) != expected_hash:
                raise ValueError("registered input mismatch")
            return path.read_bytes()
        except Exception as exc:
            if getattr(exc, "code", None) == "MVP_PATH_ESCAPE":
                raise
            raise fatal("MVP_FREEZE_INVALID", "Evaluator input failed hash verification") from exc
