from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..failures import fatal
from .hashes import bytes_sha256, file_sha256
from .resolver import resolve_relative, validate_path_identity


@dataclass(frozen=True, slots=True)
class MvpPublishReceipt:
    target_id: str
    relative_ref: str
    byte_length: int
    file_hash: str
    payload_hash: str
    parent_payload_hashes: tuple[str, ...]
    accepted: bool


class MvpImmutablePublisher:
    def __init__(self, root: Path, planned_targets: Mapping[str, str]) -> None:
        validate_path_identity(root)
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise fatal("MVP_PATH_ESCAPE", "publisher root is not an ordinary directory")
        root.mkdir(parents=True, exist_ok=True)
        folded: set[str] = set()
        validated: dict[str, str] = {}
        for target_id, relative in planned_targets.items():
            folded_ref = relative.casefold()
            if folded_ref in folded:
                raise fatal("MVP_PATH_ESCAPE", "planned targets alias under casefold")
            resolve_relative(root, relative)
            folded.add(folded_ref)
            validated[target_id] = relative.replace("\\", "/")
        self.root = root
        self._planned = validated
        self._accepted: dict[str, MvpPublishReceipt] = {}

    def publish(
        self,
        target_id: str,
        candidate: bytes,
        candidate_hash: str,
        *,
        parent_payload_hashes: tuple[str, ...] = (),
        semantic_payload_hash: str | None = None,
    ) -> MvpPublishReceipt:
        if target_id not in self._planned or target_id in self._accepted:
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "target is unplanned or already accepted")
        if bytes_sha256(candidate) != candidate_hash:
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "candidate hash does not match bytes")
        semantic_hash = candidate_hash if semantic_payload_hash is None else semantic_payload_hash
        try:
            bytes.fromhex(semantic_hash)
            parents = tuple(sorted(set(parent_payload_hashes), key=bytes.fromhex))
            if len(semantic_hash) != 64 or any(len(parent) != 64 or len(bytes.fromhex(parent)) != 32 for parent in parents):
                raise ValueError("invalid hash length")
        except ValueError as exc:
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "semantic or parent payload hash is invalid") from exc
        relative = self._planned[target_id]
        final_path = resolve_relative(self.root, relative)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                final_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            view = memoryview(candidate)
            written = 0
            while written < len(candidate):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("short immutable artifact write")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if final_path.stat().st_size != len(candidate) or file_sha256(final_path) != candidate_hash:
                raise OSError("immutable artifact read-back mismatch")
            receipt = MvpPublishReceipt(
                target_id=target_id,
                relative_ref=relative,
                byte_length=len(candidate),
                file_hash=candidate_hash,
                payload_hash=semantic_hash,
                parent_payload_hashes=parents,
                accepted=True,
            )
            self._accepted[target_id] = receipt
            return receipt
        except Exception as exc:
            if descriptor is not None:
                os.close(descriptor)
            if getattr(exc, "code", None) == "MVP_IMMUTABLE_PUBLISH_FAILED":
                raise
            raise fatal("MVP_IMMUTABLE_PUBLISH_FAILED", "immutable artifact publication failed") from exc

    def is_accepted(self, target_id: str) -> bool:
        return target_id in self._accepted

    @property
    def accepted_receipts(self) -> tuple[MvpPublishReceipt, ...]:
        return tuple(sorted(self._accepted.values(), key=lambda item: item.relative_ref.encode("utf-8")))
