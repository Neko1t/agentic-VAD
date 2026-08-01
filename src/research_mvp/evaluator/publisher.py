from __future__ import annotations

from pathlib import Path

from ..artifacts.publisher import MvpImmutablePublisher, MvpPublishReceipt
from ..artifacts.hashes import bytes_sha256


class MvpEvaluatorPublisher:
    def __init__(self, evaluation_root: Path, metrics_ref: str, receipt_ref: str) -> None:
        self._publisher = MvpImmutablePublisher(
            evaluation_root,
            {"metrics": metrics_ref, "receipt": receipt_ref},
        )

    def publish_metrics(self, payload: bytes) -> MvpPublishReceipt:
        return self._publisher.publish("metrics", payload, bytes_sha256(payload))

    def publish_receipt(self, payload: bytes) -> MvpPublishReceipt:
        return self._publisher.publish("receipt", payload, bytes_sha256(payload))
