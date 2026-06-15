from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.runtime.progress import ProgressEvent


@dataclass
class WorkflowMonitor:
    latest: dict[str, Any] | None = None
    stages: dict[str, dict[str, Any]] = field(default_factory=lambda: defaultdict(dict))
    events: list[dict[str, Any]] = field(default_factory=list)

    def consume(self, event: ProgressEvent) -> None:
        payload = {
            "stage": event.stage,
            "event": event.event,
            "message": event.message,
            "completed": event.completed,
            "total": event.total,
            "video_id": event.video_id,
            "window_id": event.window_id,
            "tool_name": event.tool_name,
            "metadata": event.metadata,
        }
        self.latest = payload
        self.events.append(payload)
        stage_state = self.stages[event.stage]
        stage_state.update(payload)

    def snapshot(self) -> dict[str, Any]:
        return {
            "latest": self.latest,
            "stages": dict(self.stages),
            "events": list(self.events),
        }


class QueueProgressReporter:
    def __init__(self, monitor: WorkflowMonitor):
        self.monitor = monitor

    def emit(self, event: ProgressEvent) -> None:
        self.monitor.consume(event)

    def close(self) -> None:
        return None
