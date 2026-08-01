from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from ..failures import fatal


def _is_reparse(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink():
        return True
    try:
        attrs = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attrs & 0x400)


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def validate_path_identity(path: Path) -> None:
    """Reject reparse traversal and case-fold aliases without resolving through them."""

    absolute = _absolute_lexical(path)
    for component in (absolute, *absolute.parents):
        if _is_reparse(component):
            raise fatal("MVP_PATH_ESCAPE", "authorized path traverses a reparse point")

    anchor = Path(absolute.anchor)
    current = anchor
    for part in absolute.parts[1:]:
        if current.exists():
            try:
                aliases = tuple(
                    child.name
                    for child in current.iterdir()
                    if child.name.casefold() == part.casefold()
                )
            except OSError as exc:
                raise fatal("MVP_PATH_ESCAPE", "authorized path identity cannot be verified") from exc
            if aliases and part not in aliases:
                raise fatal("MVP_PATH_ESCAPE", "authorized path aliases an existing component under casefold")
        current = current / part


def resolve_relative(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise fatal("MVP_PATH_ESCAPE", "artifact reference must be a non-empty relative path")
    windows = PureWindowsPath(relative)
    candidate_path = Path(relative)
    if candidate_path.is_absolute() or windows.is_absolute() or windows.drive or relative.startswith(("/", "\\")):
        raise fatal("MVP_PATH_ESCAPE", "absolute and aliased artifact paths are forbidden")
    if any(part in {"", ".", ".."} for part in windows.parts):
        raise fatal("MVP_PATH_ESCAPE", "parent and ambiguous path components are forbidden")

    validate_path_identity(root)
    root_abs = root.resolve(strict=False)
    current = root
    for part in windows.parts[:-1]:
        current = current / part
        if _is_reparse(current):
            raise fatal("MVP_PATH_ESCAPE", "reparse traversal is forbidden")
        if current.exists():
            resolved = current.resolve(strict=True)
            try:
                if os.path.commonpath((str(root_abs), str(resolved))) != str(root_abs):
                    raise fatal("MVP_PATH_ESCAPE", "artifact path escapes authorized root")
            except ValueError as exc:
                raise fatal("MVP_PATH_ESCAPE", "artifact path crosses filesystem roots") from exc

    target = root.joinpath(*windows.parts)
    target_resolved = target.resolve(strict=False)
    try:
        if os.path.commonpath((str(root_abs), str(target_resolved))) != str(root_abs):
            raise fatal("MVP_PATH_ESCAPE", "artifact path escapes authorized root")
    except ValueError as exc:
        raise fatal("MVP_PATH_ESCAPE", "artifact path crosses filesystem roots") from exc
    return target
