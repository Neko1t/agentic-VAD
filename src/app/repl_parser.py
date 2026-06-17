from __future__ import annotations

from dataclasses import dataclass
import shlex


class CommandParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]
    raw: str


_VALID_TOP_LEVEL = {
    "help",
    "doctor",
    "status",
    "download",
    "build",
    "run",
    "results",
    "compare",
    "set",
    "clear",
    "exit",
    "quit",
}


def parse_command(raw: str) -> ParsedCommand:
    stripped = raw.strip()
    if not stripped:
        raise CommandParseError("empty command")

    parts = shlex.split(stripped)
    if not parts:
        raise CommandParseError("empty command")

    command = parts[0].lower()
    if command not in _VALID_TOP_LEVEL:
        raise CommandParseError(f"unknown command: {command}")

    if command == "quit":
        command = "exit"

    return ParsedCommand(name=command, args=parts[1:], raw=raw)
