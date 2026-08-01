from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from ..codec import dumps, loads, payload_hash
from ..failures import MvpFailure, fatal
from ..ids import validate_attempt_id
from ..artifacts.resolver import validate_path_identity


FaultInjector = Callable[[str], None]


def _semantic_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    required = {
        "namespace_id",
        "version",
        "previous_snapshot_payload_hash",
        "last_committed_video_id",
        "prediction_freeze_hash",
        "cases",
        "payload_hash",
    }
    if set(snapshot) != required:
        raise fatal("MVP_MEMORY_UNAVAILABLE", "snapshot field set is invalid")
    return {key: value for key, value in snapshot.items() if key != "payload_hash"}


def _complete_snapshot(semantic: dict[str, Any]) -> dict[str, Any]:
    complete = dict(semantic)
    complete["payload_hash"] = payload_hash(semantic)
    return complete


def _read_snapshot_file(path: Path) -> dict[str, Any]:
    try:
        decoded = loads(path.read_bytes())
        if not isinstance(decoded, dict):
            raise ValueError("snapshot is not an object")
        semantic = _semantic_payload(decoded)
        if decoded["payload_hash"] != payload_hash(semantic):
            raise ValueError("snapshot payload hash mismatch")
        if not isinstance(decoded["version"], int) or decoded["version"] < 0:
            raise ValueError("snapshot version is invalid")
        if not isinstance(decoded["cases"], list):
            raise ValueError("snapshot cases are invalid")
        return decoded
    except MvpFailure:
        raise
    except Exception as exc:
        raise fatal("MVP_MEMORY_UNAVAILABLE", "snapshot read or hash verification failed") from exc


def read_snapshot(root: Path) -> dict[str, Any]:
    return _read_snapshot_file(root / "memory_snapshot.json")


def _write_fsynced_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class MvpMemoryWriter:
    def __init__(self, root: Path, namespace_id: str, capacity: int) -> None:
        self.root = root
        self.namespace_id = namespace_id
        self.capacity = capacity
        self.commit_count = 0

    @classmethod
    def create_fresh(cls, root: Path, namespace_id: str, *, capacity: int = 512) -> "MvpMemoryWriter":
        validate_attempt_id(namespace_id)
        if capacity <= 0 or capacity > 512:
            raise ValueError("MVP capacity test override must be in [1,512]")
        validate_path_identity(root)
        if root.exists() or root.is_symlink():
            raise fatal("MVP_MEMORY_UNAVAILABLE", "reference namespace must be fresh and absent")
        try:
            root.mkdir(parents=True, exist_ok=False)
            (root / "audit").mkdir()
            (root / "staging").mkdir()
            genesis = _complete_snapshot(
                {
                    "namespace_id": namespace_id,
                    "version": 0,
                    "previous_snapshot_payload_hash": None,
                    "last_committed_video_id": None,
                    "prediction_freeze_hash": None,
                    "cases": [],
                }
            )
            _write_fsynced_exclusive(root / "memory_snapshot.json", dumps(genesis))
            _read_snapshot_file(root / "memory_snapshot.json")
        except MvpFailure:
            raise
        except Exception as exc:
            raise fatal("MVP_MEMORY_COMMIT_FAILED", "genesis snapshot publication failed") from exc
        return cls(root, namespace_id, capacity)

    def commit_video(
        self,
        *,
        video_id: str,
        prediction_freeze_hash: str,
        prediction_freeze_accepted: bool,
        candidates: tuple[dict[str, Any], ...],
        fault_injector: FaultInjector | None = None,
    ) -> dict[str, Any]:
        if not prediction_freeze_accepted or len(prediction_freeze_hash) != 64:
            raise fatal("MVP_FREEZE_INVALID", "Memory commit requires an accepted complete PredictionFreeze")
        current = read_snapshot(self.root)
        if current["namespace_id"] != self.namespace_id:
            raise fatal("MVP_MEMORY_UNAVAILABLE", "snapshot namespace mismatch")
        existing_ids = {case["case_id"] for case in current["cases"]}
        additions: list[dict[str, Any]] = []
        for case in candidates:
            if case.get("source_video_id") != video_id:
                raise fatal("MVP_MEMORY_COMMIT_FAILED", "candidate source video mismatch")
            if case.get("derivation") != "LOCAL_FINAL_B2_ONLY":
                raise fatal("MVP_MEMORY_COMMIT_FAILED", "candidate derivation is not local-final-B2-only")
            if case.get("source_prediction_freeze_hash") != prediction_freeze_hash:
                raise fatal("MVP_MEMORY_COMMIT_FAILED", "candidate PredictionFreeze binding mismatch")
            if case.get("case_id") in existing_ids or any(item["case_id"] == case.get("case_id") for item in additions):
                raise fatal("MVP_MEMORY_COMMIT_FAILED", "duplicate case identity")
            additions.append(dict(case))
        cases = sorted([*current["cases"], *additions], key=lambda case: str(case["case_id"]).encode("utf-8"))
        if len(cases) > self.capacity:
            raise fatal("MVP_CAPACITY_EXCEEDED", "snapshot capacity would exceed the frozen bound")
        next_snapshot = _complete_snapshot(
            {
                "namespace_id": self.namespace_id,
                "version": current["version"] + 1,
                "previous_snapshot_payload_hash": current["payload_hash"],
                "last_committed_video_id": video_id,
                "prediction_freeze_hash": prediction_freeze_hash,
                "cases": cases,
            }
        )
        staging = self.root / "staging" / f"memory_snapshot.{next_snapshot['version']:08d}.json"
        replaced = False
        try:
            encoded = dumps(next_snapshot)
            _write_fsynced_exclusive(staging, encoded)
            reread = _read_snapshot_file(staging)
            if reread != next_snapshot or staging.read_bytes() != encoded:
                raise OSError("staging verification mismatch")
            if fault_injector is not None:
                fault_injector("before_replace")
            os.replace(staging, self.root / "memory_snapshot.json")
            replaced = True
            self.commit_count += 1
            committed = read_snapshot(self.root)
            if committed != next_snapshot:
                raise OSError("committed snapshot verification mismatch")
            if fault_injector is not None:
                fault_injector("before_audit")
            audit = {
                "snapshot_payload_hash": committed["payload_hash"],
                "version": committed["version"],
                "video_id": video_id,
                "prediction_freeze_hash": prediction_freeze_hash,
            }
            audit_path = self.root / "audit" / "video_commits.jsonl"
            with audit_path.open("ab") as stream:
                stream.write(dumps(audit) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            return committed
        except MvpFailure:
            raise
        except Exception as exc:
            if replaced:
                raise fatal("MVP_MEMORY_AUDIT_INCOMPLETE", "snapshot committed but audit projection failed") from exc
            raise fatal("MVP_MEMORY_COMMIT_FAILED", "snapshot failed before the atomic replace") from exc
