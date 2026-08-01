from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..artifacts.hashes import file_sha256
from ..artifacts.publisher import MvpImmutablePublisher, MvpPublishReceipt
from ..codec import dumps, payload_hash
from ..contracts import MvpInferenceFreeze, MvpMemoryFreeze, MvpOutputHashManifest


def publish_output_manifest(
    publisher: MvpImmutablePublisher,
    *,
    attempt_id: str,
    excluded_target_ids: set[str],
) -> tuple[MvpOutputHashManifest, MvpPublishReceipt]:
    entries = tuple(
        {
            "artifact_type": receipt.target_id.split(":", 1)[0],
            "byte_length": receipt.byte_length,
            "parent_payload_hashes": list(receipt.parent_payload_hashes),
            "relative_ref": receipt.relative_ref,
            "sha256": receipt.file_hash,
        }
        for receipt in publisher.accepted_receipts
        if receipt.target_id not in excluded_target_ids
    )
    semantic = {"entries": entries}
    manifest = MvpOutputHashManifest(attempt_id, entries, payload_hash(semantic))
    encoded = dumps(asdict(manifest))
    receipt = publisher.publish(
        "freeze:output",
        encoded,
        payload_hash(asdict(manifest)),
        parent_payload_hashes=tuple(entry["sha256"] for entry in entries),
        semantic_payload_hash=manifest.payload_hash,
    )
    return manifest, receipt


def publish_memory_freeze(
    publisher: MvpImmutablePublisher,
    *,
    namespace_id: str,
    snapshot: dict[str, Any],
    snapshot_path: Path,
) -> tuple[MvpMemoryFreeze, MvpPublishReceipt]:
    freeze = MvpMemoryFreeze(
        namespace_id=namespace_id,
        snapshot_payload_hash=str(snapshot["payload_hash"]),
        snapshot_file_hash=file_sha256(snapshot_path),
        version=int(snapshot["version"]),
    )
    receipt = publisher.publish(
        "freeze:memory",
        dumps(asdict(freeze)),
        payload_hash(asdict(freeze)),
        parent_payload_hashes=(str(snapshot["payload_hash"]),),
    )
    return freeze, receipt


def publish_inference_freeze(
    publisher: MvpImmutablePublisher,
    *,
    attempt_id: str,
    prediction_freeze_hashes: tuple[str, ...],
    output_manifest_hash: str,
    memory_freeze_hash: str,
) -> tuple[MvpInferenceFreeze, MvpPublishReceipt]:
    freeze = MvpInferenceFreeze(
        attempt_id=attempt_id,
        prediction_freeze_hashes=prediction_freeze_hashes,
        output_manifest_hash=output_manifest_hash,
        memory_freeze_hash=memory_freeze_hash,
    )
    receipt = publisher.publish(
        "freeze:inference",
        dumps(asdict(freeze)),
        payload_hash(asdict(freeze)),
        parent_payload_hashes=(*prediction_freeze_hashes, output_manifest_hash, memory_freeze_hash),
        semantic_payload_hash=payload_hash(
            {
                "memory_freeze_hash": memory_freeze_hash,
                "output_manifest_hash": output_manifest_hash,
                "prediction_freeze_hashes": list(prediction_freeze_hashes),
            }
        ),
    )
    return freeze, receipt
