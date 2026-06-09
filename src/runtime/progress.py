from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


@dataclass(slots=True)
class ProgressEvent:
    stage: str
    event: str
    message: str = ""
    completed: int | None = None
    total: int | None = None
    video_id: str | None = None
    window_id: str | None = None
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProgressReporter(Protocol):
    def emit(self, event: ProgressEvent) -> None:
        ...

    def close(self) -> None:
        ...


class NullProgressReporter:
    def emit(self, event: ProgressEvent) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "NullProgressReporter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class PrefixedProgressReporter:
    def __init__(self, reporter: ProgressReporter, prefix: str):
        self.reporter = reporter
        self.prefix = prefix.strip()

    def emit(self, event: ProgressEvent) -> None:
        message = event.message
        if self.prefix:
            message = f"{self.prefix} | {message}" if message else self.prefix
        self.reporter.emit(replace(event, message=message))

    def close(self) -> None:
        self.reporter.close()


class RichProgressReporter:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("{task.fields[detail]}"),
            console=self.console,
            transient=False,
            expand=True,
        )
        self._task_id: int | None = None
        self._started = False

    def __enter__(self) -> "RichProgressReporter":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._started:
            return
        self.progress.start()
        self._task_id = self.progress.add_task("agentic-vad", total=1, completed=0, detail="")
        self._started = True

    def emit(self, event: ProgressEvent) -> None:
        if not self._started:
            self.start()
        assert self._task_id is not None
        description = self._build_description(event)
        detail = self._build_detail(event)
        update_args: dict[str, Any] = {"description": description, "detail": detail}
        if event.total is not None:
            update_args["total"] = max(1, event.total)
        if event.completed is not None:
            update_args["completed"] = max(0, event.completed)
        self.progress.update(self._task_id, **update_args)
        self.progress.refresh()

    def close(self) -> None:
        if not self._started:
            return
        self.progress.stop()
        self._started = False

    def _build_description(self, event: ProgressEvent) -> str:
        stage = event.stage.replace("_", " ")
        if event.tool_name:
            return f"{stage}: {event.tool_name}"
        if event.message:
            return f"{stage}: {event.message}"
        return stage

    def _build_detail(self, event: ProgressEvent) -> str:
        parts: list[str] = []
        if event.video_id:
            parts.append(f"video={event.video_id}")
        if event.window_id:
            parts.append(f"window={event.window_id}")
        if event.message and not event.tool_name:
            parts.append(event.message)
        elif event.message and event.tool_name:
            parts.append(event.message)
        if not parts and event.event:
            parts.append(event.event.replace("_", " "))
        return " | ".join(parts)
